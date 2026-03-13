# Cryptography Migration Workflow: `pycryptodomex` to `cryptography` (pyca)

## Goal

Replace `pycryptodomex` with `cryptography` (pyca) across NPPS4, driven by the iOS feasibility requirement (iOS wheels available for `cryptography` but not for `pycryptodomex`), without regressing the existing server and with the opportunity to improve correctness.

---

## Scope of Change

### Files that import `Cryptodome` directly

| File | Operations |
|---|---|
| `npps4/util.py` | RSA sign (SHA1+PKCS1v1.5), RSA decrypt (PKCS1v1.5), AES-CBC decrypt |
| `npps4/data/schema.py` | PBKDF2-SHA256 key derivation, AES-CTR encrypt/decrypt, SHA256 hashing |
| `npps4/config/config.py` | RSA private key loading from PEM |
| `make_server_key.py` | RSA key generation + PEM export |
| `util/decrypt_db_row.py` | AES-CBC decrypt (already has `cryptography` fallback) |

### Files that use only `hashlib`/`hmac` (stdlib) — no changes needed

`npps4/db/main.py`, `npps4/system/lila.py`, `npps4/system/handover.py`, `npps4/system/live.py`, `npps4/errhand.py`, `npps4/svinfo.py`

---

## Workflow: Dual-Backend with Test Harness

The key insight: we can run **both** libraries side-by-side, compare their outputs on every operation, and only remove `pycryptodomex` once we have proof that every operation is byte-identical. This turns the migration from a "hope nothing breaks" swap into a verified, incremental transition.

### Phase 1: Build a Crypto Test Harness (no production changes)

**Goal**: Capture real cryptographic inputs/outputs as test vectors, then verify the new `cryptography` backend reproduces them exactly.

#### Step 1.1 — Collect test vectors from the running server

Create `tests/crypto_vectors.py` that exercises every crypto operation with known inputs and records expected outputs:

```python
"""
Generate and verify crypto test vectors for the pycryptodomex -> cryptography migration.
Run this BEFORE any migration to capture the ground truth from the current implementation.
"""
import base64
import json
import os

import Cryptodome.Cipher.AES
import Cryptodome.Cipher.PKCS1_v1_5
import Cryptodome.Hash.SHA1
import Cryptodome.Hash.SHA256
import Cryptodome.Protocol.KDF
import Cryptodome.PublicKey.RSA
import Cryptodome.Signature.pkcs1_15
import Cryptodome.Util.Padding

VECTORS_FILE = os.path.join(os.path.dirname(__file__), "crypto_test_vectors.json")

def generate_test_key():
    """Generate a deterministic-ish RSA key for test use only."""
    # Use a fixed test key (NOT the server key) for reproducibility
    key = Cryptodome.PublicKey.RSA.generate(1024)
    return key

def collect_vectors():
    vectors = {}
    key = generate_test_key()
    key_pem = key.export_key("PEM")
    pub_pem = key.public_key().export_key("PEM")
    vectors["rsa_private_key_pem"] = base64.b64encode(key_pem).decode()
    vectors["rsa_public_key_pem"] = base64.b64encode(pub_pem).decode()

    # --- RSA Sign (SHA1 + PKCS1v1.5) ---
    sign_data = b"test message for signing"
    sha1 = Cryptodome.Hash.SHA1.new(sign_data)
    signer = Cryptodome.Signature.pkcs1_15.new(key)
    signature = signer.sign(sha1)
    vectors["rsa_sign"] = {
        "input": base64.b64encode(sign_data).decode(),
        "signature": base64.b64encode(signature).decode(),
    }

    # --- RSA Decrypt (PKCS1v1.5) ---
    from Cryptodome.Cipher import PKCS1_v1_5 as PKCS1_Cipher
    plaintext = b"secret payload 16"  # short enough for 1024-bit RSA
    cipher = PKCS1_Cipher.new(key.public_key())
    ciphertext = cipher.encrypt(plaintext)
    vectors["rsa_decrypt"] = {
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "plaintext": base64.b64encode(plaintext).decode(),
    }

    # --- AES-CBC decrypt ---
    aes_key = os.urandom(16)
    iv = os.urandom(16)
    aes_plaintext = b"hello AES-CBC!!\x00"  # 16 bytes
    padded = Cryptodome.Util.Padding.pad(aes_plaintext, 16)
    aes_obj = Cryptodome.Cipher.AES.new(aes_key, Cryptodome.Cipher.AES.MODE_CBC, iv=iv)
    aes_ciphertext = iv + aes_obj.encrypt(padded)
    vectors["aes_cbc"] = {
        "key": base64.b64encode(aes_key).decode(),
        "ciphertext_with_iv": base64.b64encode(aes_ciphertext).decode(),
        "plaintext": base64.b64encode(aes_plaintext).decode(),
    }

    # --- AES-CTR encrypt/decrypt ---
    ctr_key = os.urandom(16)
    nonce = os.urandom(8)
    ctr_plaintext = b"hello AES-CTR mode"
    aes_ctr = Cryptodome.Cipher.AES.new(
        ctr_key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce
    )
    ctr_ciphertext = aes_ctr.encrypt(ctr_plaintext)
    vectors["aes_ctr"] = {
        "key": base64.b64encode(ctr_key).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "plaintext": base64.b64encode(ctr_plaintext).decode(),
        "ciphertext": base64.b64encode(ctr_ciphertext).decode(),
    }

    # --- PBKDF2-SHA256 ---
    password = b"serial_code_password"
    salt = os.urandom(16)
    derived = Cryptodome.Protocol.KDF.PBKDF2(
        password, salt, dkLen=16, count=10000,
        prf=lambda p, s: Cryptodome.Hash.SHA256.new(p + s).digest()
        # Note: NPPS4 uses hmac_hash_module=Cryptodome.Hash.SHA256
    )
    vectors["pbkdf2"] = {
        "password": base64.b64encode(password).decode(),
        "salt": base64.b64encode(salt).decode(),
        "iterations": 10000,
        "dk_len": 16,
        "derived_key": base64.b64encode(derived).decode(),
    }

    return vectors

def save_vectors():
    vectors = collect_vectors()
    with open(VECTORS_FILE, "w") as f:
        json.dump(vectors, f, indent=2)
    print(f"Saved {len(vectors)} vector groups to {VECTORS_FILE}")

if __name__ == "__main__":
    save_vectors()
```

Run this once against the current codebase to produce `tests/crypto_test_vectors.json` — the **ground truth**.

#### Step 1.2 — Write verification tests against the `cryptography` backend

Create `tests/test_crypto_migration.py`:

```python
"""
Verify that the `cryptography` (pyca) backend produces byte-identical results
to the pycryptodomex backend, using vectors captured by crypto_vectors.py.
"""
import base64
import json
import os
import pytest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

VECTORS_FILE = os.path.join(os.path.dirname(__file__), "crypto_test_vectors.json")

@pytest.fixture(scope="module")
def vectors():
    with open(VECTORS_FILE) as f:
        return json.load(f)

@pytest.fixture(scope="module")
def rsa_key(vectors):
    pem = base64.b64decode(vectors["rsa_private_key_pem"])
    return serialization.load_pem_private_key(pem, password=None)

def test_rsa_sign(vectors, rsa_key):
    data = base64.b64decode(vectors["rsa_sign"]["input"])
    expected_sig = base64.b64decode(vectors["rsa_sign"]["signature"])

    signature = rsa_key.sign(data, padding.PKCS1v15(), hashes.SHA1())
    assert signature == expected_sig, "RSA signature mismatch"

def test_rsa_decrypt(vectors, rsa_key):
    ciphertext = base64.b64decode(vectors["rsa_decrypt"]["ciphertext"])
    expected_pt = base64.b64decode(vectors["rsa_decrypt"]["plaintext"])

    plaintext = rsa_key.decrypt(ciphertext, padding.PKCS1v15())
    assert plaintext == expected_pt, "RSA decrypt mismatch"

def test_aes_cbc_decrypt(vectors):
    key = base64.b64decode(vectors["aes_cbc"]["key"])
    ct_with_iv = base64.b64decode(vectors["aes_cbc"]["ciphertext_with_iv"])
    expected_pt = base64.b64decode(vectors["aes_cbc"]["plaintext"])

    iv, ct = ct_with_iv[:16], ct_with_iv[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    plaintext = padded[: -padded[-1]]  # PKCS7 unpad (matching NPPS4's manual unpad)
    assert plaintext == expected_pt, "AES-CBC decrypt mismatch"

def test_aes_ctr(vectors):
    key = base64.b64decode(vectors["aes_ctr"]["key"])
    nonce = base64.b64decode(vectors["aes_ctr"]["nonce"])
    plaintext = base64.b64decode(vectors["aes_ctr"]["plaintext"])
    expected_ct = base64.b64decode(vectors["aes_ctr"]["ciphertext"])

    # NOTE: pycryptodomex CTR nonce handling differs from pyca.
    # Cryptodome: AES.new(key, MODE_CTR, nonce=nonce) uses nonce || counter
    #   where nonce is len(nonce) bytes and counter fills the rest of the 16-byte block.
    # pyca: modes.CTR(nonce) expects a full 16-byte IV (nonce || initial_counter).
    # Cryptodome with nonce=8 bytes -> 8 bytes nonce + 8 bytes counter (big-endian, starting at 0)
    full_nonce = nonce + b"\x00" * (16 - len(nonce))
    cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    assert ciphertext == expected_ct, "AES-CTR encrypt mismatch"

def test_pbkdf2(vectors):
    password = base64.b64decode(vectors["pbkdf2"]["password"])
    salt = base64.b64decode(vectors["pbkdf2"]["salt"])
    iterations = vectors["pbkdf2"]["iterations"]
    dk_len = vectors["pbkdf2"]["dk_len"]
    expected_dk = base64.b64decode(vectors["pbkdf2"]["derived_key"])

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=dk_len,
        salt=salt,
        iterations=iterations,
    )
    derived = kdf.derive(password)
    assert derived == expected_dk, "PBKDF2 key derivation mismatch"
```

**Critical discovery opportunity**: The AES-CTR nonce handling test is where a subtle bug would surface. PyCryptodome's `nonce=` parameter with an 8-byte value zero-fills the remaining counter bytes. The `cryptography` library's `modes.CTR()` expects the full 16-byte IV. If `schema.py` uses a different nonce length, this test will catch the incompatibility immediately. Verify what `schema.py` actually passes — this is where the migration can **improve** correctness by making the nonce handling explicit.

#### Step 1.3 — Verify PBKDF2 PRF compatibility

This is the most likely divergence point. Check `schema.py`'s actual PBKDF2 call:

```python
# schema.py currently uses:
Cryptodome.Protocol.KDF.PBKDF2(password, salt, dkLen=16, count=N,
                                 hmac_hash_module=Cryptodome.Hash.SHA256)
```

`PBKDF2HMAC` in `cryptography` uses HMAC-SHA256 by default when you pass `hashes.SHA256()`. This is the standard PBKDF2. But if the PyCryptodome call uses `prf=` (a custom PRF lambda) instead of `hmac_hash_module=`, the output **will differ** — `prf=` in PyCryptodome defaults to HMAC-SHA1 when omitted. The test vectors catch this.

---

### Phase 2: Introduce a Thin Crypto Abstraction Layer

**Goal**: Decouple NPPS4's business logic from the specific crypto library, enabling side-by-side comparison and future backend swaps.

Create `npps4/crypto.py` — a single module that wraps all crypto operations:

```python
"""
Thin crypto abstraction for NPPS4.
Provides all cryptographic operations used by the server.

During migration: can run both backends and assert equivalence.
After migration: only the `cryptography` backend remains.
"""
from __future__ import annotations

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def load_rsa_private_key(pem_data: bytes, password: str | None = None):
    pwd = password.encode() if password else None
    return serialization.load_pem_private_key(pem_data, password=pwd)


def generate_rsa_key(bits: int = 1024):
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def export_rsa_private_pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


def export_rsa_public_pem(key) -> bytes:
    pub = key.public_key()
    return pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def rsa_sign_sha1(key, data: bytes) -> bytes:
    return key.sign(data, asym_padding.PKCS1v15(), hashes.SHA1())


def rsa_decrypt_pkcs1v15(key, ciphertext: bytes) -> bytes:
    return key.decrypt(ciphertext, asym_padding.PKCS1v15())


def aes_cbc_decrypt(key: bytes, data: bytes) -> bytes:
    """Decrypt AES-CBC. `data` = IV (16 bytes) || ciphertext. Manual PKCS7 unpad."""
    iv, ct = data[:16], data[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    return padded[: -padded[-1]]


def aes_ctr_cipher(key: bytes, nonce: bytes):
    """Return an AES-CTR encryptor/decryptor. Caller uses .update() + .finalize()."""
    # PyCryptodome nonce= with N-byte value zero-pads the counter portion.
    full_nonce = nonce + b"\x00" * (16 - len(nonce))
    cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
    return cipher


def pbkdf2_sha256(password: bytes, salt: bytes, iterations: int, length: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=length, salt=salt, iterations=iterations
    )
    return kdf.derive(password)


def sha256_digest(data: bytes) -> bytes:
    h = hashes.Hash(hashes.SHA256())
    h.update(data)
    return h.finalize()
```

This layer:
- Is **testable in isolation** against the test vectors
- Makes the migration a series of **import swaps**, not crypto re-implementations
- Documents every nonce/padding convention in one place (improvement over scattered implicit conventions)

---

### Phase 3: Dual-Run Mode (the safety net)

**Goal**: During development, run both backends on every request and assert equivalence. This catches any edge case the static test vectors missed.

Add a temporary dual-run wrapper (only during development, controlled by an env var):

```python
# npps4/crypto.py (during migration only)
import os
DUAL_RUN = os.environ.get("NPPS4_CRYPTO_DUAL_RUN", "0") == "1"

if DUAL_RUN:
    import Cryptodome.Cipher.AES
    import Cryptodome.Cipher.PKCS1_v1_5
    import Cryptodome.Hash.SHA1
    import Cryptodome.Signature.pkcs1_15
    import logging

    _log = logging.getLogger("npps4.crypto.dual")

    _original_aes_cbc_decrypt = aes_cbc_decrypt

    def aes_cbc_decrypt(key: bytes, data: bytes) -> bytes:
        new_result = _original_aes_cbc_decrypt(key, data)

        # Old backend
        aes = Cryptodome.Cipher.AES.new(key, Cryptodome.Cipher.AES.MODE_CBC, iv=data[:16])
        old_padded = aes.decrypt(data[16:])
        old_result = old_padded[: -old_padded[-1]]

        if new_result != old_result:
            _log.error("AES-CBC MISMATCH: key=%s len(data)=%d", key.hex(), len(data))
            raise RuntimeError("Crypto migration: AES-CBC output mismatch")
        return new_result

    # (Similar wrappers for rsa_sign_sha1, rsa_decrypt_pkcs1v15, etc.)
```

Run the full server with `NPPS4_CRYPTO_DUAL_RUN=1` during testing. Every request exercises both backends. If anything diverges, it logs the exact operation and inputs for debugging.

---

### Phase 4: Swap Imports (the actual migration)

With Phase 1-3 giving confidence, the file changes are mechanical:

#### `npps4/config/config.py`
```python
# Before:
import Cryptodome.PublicKey.RSA
_SERVER_KEY = Cryptodome.PublicKey.RSA.import_key(f.read(), key_password)

# After:
from . import crypto
_SERVER_KEY = crypto.load_rsa_private_key(f.read(), key_password)
```

#### `npps4/util.py`
```python
# Before:
import Cryptodome.Cipher.PKCS1_v1_5
import Cryptodome.Cipher.AES
import Cryptodome.Hash.SHA1
import Cryptodome.Util.Padding
import Cryptodome.Signature.pkcs1_15

def sign_message(content, request_xmc_hex):
    sha1 = Cryptodome.Hash.SHA1.new(content)
    if request_xmc_hex is not None:
        sha1.update(request_xmc_hex.encode("UTF-8"))
    sign = Cryptodome.Signature.pkcs1_15.new(config.get_server_rsa())
    return str(base64.b64encode(sign.sign(sha1)), "UTF-8")

# After:
from . import crypto

def sign_message(content, request_xmc_hex):
    data = content
    if request_xmc_hex is not None:
        data = content + request_xmc_hex.encode("UTF-8")
    sig = crypto.rsa_sign_sha1(config.get_server_rsa(), data)
    return str(base64.b64encode(sig), "UTF-8")
```

**Improvement opportunity**: The current `sign_message` feeds data to SHA1 in two steps (`.new(content)` then `.update(xmc)`). The `cryptography` library's `key.sign()` hashes internally, so we concatenate first. The test vectors from Phase 1 verify this produces identical signatures.

#### `npps4/data/schema.py`
```python
# Before:
import Cryptodome.Cipher.AES
import Cryptodome.Hash.SHA256
import Cryptodome.Protocol.KDF

# After:
from .. import crypto
# Use crypto.pbkdf2_sha256(), crypto.aes_ctr_cipher(), crypto.sha256_digest()
```

#### `make_server_key.py`
```python
# Before:
import Cryptodome.PublicKey.RSA
key = Cryptodome.PublicKey.RSA.generate(1024)

# After:
from npps4 import crypto
key = crypto.generate_rsa_key(1024)
```

#### `util/decrypt_db_row.py`
Already has a `cryptography` fallback — just promote it to the primary and remove the Cryptodome branches.

#### `requirements.txt`
```diff
-pycryptodomex
+cryptography
```

Add iOS platform marker:
```
cryptography; sys_platform != 'ios'
cryptography; sys_platform == 'ios'
```
(Both resolve the same package, but the iOS wheel is sourced from BeeWare's index during iOS builds.)

---

### Phase 5: Validation Checklist

Before removing `pycryptodomex` from requirements:

- [ ] `tests/test_crypto_migration.py` passes with all vector groups
- [ ] Full server boot with `NPPS4_CRYPTO_DUAL_RUN=1` — no mismatches logged
- [ ] Game client can connect and complete:
  - [ ] Login handshake (RSA decrypt + AES-CBC decrypt of session key)
  - [ ] API request/response cycle (X-Message-Sign RSA signature verification)
  - [ ] Live show (verifies no runtime errors in hot path)
  - [ ] Transfer code generation/use (SHA1 hashing in `handover.py` — stdlib, but verify the flow)
  - [ ] Serial code redemption (PBKDF2 + AES-CTR in `schema.py`)
- [ ] `util/decrypt_db_row.py` successfully decrypts a test database
- [ ] `make_server_key.py` generates a key that the server can load and the client accepts
- [ ] Dual-run wrapper removed, `pycryptodomex` removed from requirements
- [ ] CI (if any) passes

---

### Phase 6: Cleanup

- Remove `NPPS4_CRYPTO_DUAL_RUN` dual-run code from `npps4/crypto.py`
- Remove `pycryptodomex` from `requirements.txt`
- Keep `tests/test_crypto_migration.py` and `tests/crypto_test_vectors.json` as regression tests

---

## How This Workflow Improves Over a Direct Swap

| Concern | Direct swap | This workflow |
|---|---|---|
| Nonce/IV handling differences | Discovered in production | Caught by test vectors in Phase 1 |
| PBKDF2 PRF mismatch | Silent wrong keys | Caught by PBKDF2 vector comparison |
| RSA padding edge cases | Client rejects signatures | Caught by dual-run in Phase 3 |
| AES-CTR counter semantics | Corrupted serial codes | Explicit in `crypto.py`, tested |
| Regression after migration | Unknown | Permanent test suite from Phase 1 |
| Future library swap | Another risky migration | Abstraction layer absorbs it |

## Specific Improvement Opportunities

1. **Explicit nonce handling**: PyCryptodome's `nonce=` parameter silently zero-pads the counter. The `cryptography` migration forces this to be explicit (`nonce + b"\x00" * (16 - len(nonce))`), making the code self-documenting.

2. **PBKDF2 correctness**: Verify that `schema.py` uses `hmac_hash_module=` (HMAC-SHA256, standard PBKDF2) and not `prf=` (custom PRF). If it uses `prf=`, the current implementation may actually be non-standard, and the migration is an opportunity to fix it.

3. **RSA sign data flow**: The current two-step hash (`SHA1.new(content).update(xmc)`) is correct but fragile. The `cryptography` API hashes internally from concatenated data, which is clearer.

4. **Padding removal**: `decrypt_aes` in `util.py` does manual PKCS7 unpadding (`data[:-data[-1]]`). This doesn't validate that all padding bytes are correct (a malformed padding like `\x03\x01\x03` would silently produce wrong output). The `cryptography` library offers proper `PKCS7` unpadding that validates — consider using it for strictness. However, since the current code works and changing padding behavior could break compatibility with existing encrypted data, keep the manual unpad to match existing behavior exactly.

5. **Centralized crypto**: Scattering `Cryptodome.*` imports across 5 files means each file independently handles padding, modes, etc. The `npps4/crypto.py` module centralizes these decisions.
