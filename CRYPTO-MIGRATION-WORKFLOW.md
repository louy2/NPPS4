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

## Strategy: Test-Vector Harness

Instead of a full abstraction layer + dual-run runtime, the migration safety comes from a **test-vector harness** — a pair of scripts that capture the ground truth from pycryptodomex, then prove `cryptography` reproduces it byte-for-byte. This is lighter weight, doesn't touch production code until the swap itself, and still catches every known class of migration bug.

### What the harness covers

| Test class | What it proves | Migration risk it catches |
|---|---|---|
| `TestRSASign` (with and without xmc) | `key.sign(content + xmc, PKCS1v15(), SHA1())` == two-step `SHA1.new(content).update(xmc)` + `pkcs1_15.sign()` | SHA1 incremental vs. concatenated hashing divergence |
| `TestRSADecrypt` | `key.decrypt(ct, PKCS1v15())` == `PKCS1_v1_5.new(key).decrypt(ct, None)` | PKCS#1 v1.5 padding implementation differences |
| `TestAESCBC` | CBC decrypt with manual PKCS7 unpad matches | IV extraction, padding removal |
| `TestAESCTR` (encrypt + decrypt) | `modes.CTR(nonce \|\| 0x00*8)` == `MODE_CTR, nonce=nonce, initial_value=0` | **The critical one**: PyCryptodome's `nonce=` silently zero-pads the counter half; `cryptography` expects a full 16-byte IV |
| `TestPBKDF2` | `PBKDF2HMAC(SHA256())` == `PBKDF2(hmac_hash_module=SHA256)` | `hmac_hash_module=` vs `prf=` semantics (different PRFs, different outputs) |
| `TestSerialCodeFlow` | End-to-end: PBKDF2 → xor nonce → AES-CTR decrypt | Composition bugs where individual ops are correct but chaining is wrong |
| `TestRSAKeyLoading` | PEM loading with/without password | Passphrase encoding, key format compatibility |
| `TestRSAKeyGeneration` | PyCryptodome PEM round-trips through `cryptography` loader | PEM format compatibility (TraditionalOpenSSL vs PKCS8) |
| `TestDecryptDBRow` | Same as AES-CBC (confirms the fallback path in `decrypt_db_row.py` is correct) | Redundant by design — this file already has a `cryptography` fallback |

---

## How to Use

### Step 1: Generate vectors (run once, before any migration)

```bash
python -m tests.generate_crypto_vectors
```

This runs every crypto operation through the **current** pycryptodomex code and saves the inputs + outputs to `tests/crypto_test_vectors.json`. The vectors file is committed so it survives the library swap.

### Step 2: Run the verification tests

```bash
python -m pytest tests/test_crypto_migration.py -v
```

Both libraries can be installed simultaneously — they don't conflict. Every test takes a pycryptodomex-generated vector and re-derives the output using only `cryptography` APIs, asserting byte equality.

**Current status: 15/15 tests passing.**

### Step 3: Swap the imports

With the tests green, the actual migration in each file is mechanical:

#### `npps4/util.py`

```python
# Before:
sha1 = Cryptodome.Hash.SHA1.new(content)
if request_xmc_hex is not None:
    sha1.update(request_xmc_hex.encode("UTF-8"))
sign = Cryptodome.Signature.pkcs1_15.new(config.get_server_rsa())
return str(base64.b64encode(sign.sign(sha1)), "UTF-8")

# After:
data = content
if request_xmc_hex is not None:
    data = content + request_xmc_hex.encode("UTF-8")
sig = config.get_server_rsa().sign(data, asym_padding.PKCS1v15(), hashes.SHA1())
return str(base64.b64encode(sig), "UTF-8")
```

The test `TestRSASign::test_sign_with_xmc` proves the two-step hash and the concatenation produce identical signatures.

#### `npps4/util.py` — `decrypt_rsa`

```python
# Before:
pkcs = Cryptodome.Cipher.PKCS1_v1_5.new(config.get_server_rsa())
return pkcs.decrypt(data, None)

# After:
return config.get_server_rsa().decrypt(data, asym_padding.PKCS1v15())
```

#### `npps4/util.py` — `decrypt_aes`

```python
# Before:
aes = Cryptodome.Cipher.AES.new(key, Cryptodome.Cipher.AES.MODE_CBC, iv=data[:16])
data = aes.decrypt(data[16:])
return data[: -data[-1]]

# After:
cipher = Cipher(algorithms.AES(key), modes.CBC(data[:16]))
decryptor = cipher.decryptor()
padded = decryptor.update(data[16:]) + decryptor.finalize()
return padded[: -padded[-1]]
```

#### `npps4/config/config.py`

```python
# Before:
import Cryptodome.PublicKey.RSA
_SERVER_KEY = Cryptodome.PublicKey.RSA.import_key(f.read(), key_password)

# After:
from cryptography.hazmat.primitives.serialization import load_pem_private_key
pwd = key_password.encode() if key_password else None
_SERVER_KEY = load_pem_private_key(f.read(), password=pwd)
```

#### `npps4/data/schema.py` — `derive_serial_code_action_key`

```python
# Before:
Cryptodome.Protocol.KDF.PBKDF2(password, salt, 16, 4, hmac_hash_module=SHA256)

# After:
kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=16, salt=salt, iterations=4)
kdf.derive(password)
```

#### `npps4/data/schema.py` — `initialize_aes_for_action_field`

```python
# Before:
Cryptodome.Cipher.AES.new(key, MODE_CTR, nonce=xorbytes(salt[:8], salt[8:]), initial_value=0)

# After:
nonce = xorbytes(salt[:8], salt[8:])
full_nonce = nonce + b"\x00" * 8  # Explicit: 8-byte nonce || 8-byte zero counter
cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
# Return cipher.encryptor() or cipher.decryptor() as needed
```

The test `TestAESCTR` proves the nonce expansion produces identical ciphertext.

#### `make_server_key.py`

```python
# Before:
key = Cryptodome.PublicKey.RSA.generate(1024)
key.export_key("PEM")
key.public_key().export_key("PEM")

# After:
from cryptography.hazmat.primitives.asymmetric import rsa
key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
```

`TestRSAKeyGeneration` proves the PEM formats are cross-compatible.

#### `util/decrypt_db_row.py`

Already has a `cryptography` fallback — promote it to the only implementation and remove the Cryptodome/Crypto branches.

#### `requirements.txt`

```diff
-pycryptodomex
+cryptography
```

### Step 4: Re-run the tests

```bash
python -m pytest tests/test_crypto_migration.py -v
```

The vectors file was generated from pycryptodomex. After the swap, the tests prove `cryptography` still produces identical outputs. The test suite becomes a permanent regression guard.

### Step 5: Manual validation checklist

Before final merge:

- [ ] `pytest tests/test_crypto_migration.py` — 15/15 pass
- [ ] Server boots and loads the RSA key
- [ ] Game client login handshake succeeds (RSA decrypt + AES-CBC)
- [ ] API responses have valid X-Message-Sign (RSA sign)
- [ ] Serial code redemption works (PBKDF2 + AES-CTR)
- [ ] `make_server_key.py` generates a usable key
- [ ] `util/decrypt_db_row.py` decrypts a test database

---

## What the Tests Discovered

The harness already surfaced and **confirmed safe** three subtle API differences:

1. **AES-CTR nonce expansion**: PyCryptodome's `nonce=` (8 bytes) + `initial_value=0` internally builds a 16-byte IV as `nonce || 0x0000000000000000`. The `cryptography` API requires the full 16-byte IV directly. The fix is `nonce + b"\x00" * 8` — the test proves this matches.

2. **RSA sign hashing**: PyCryptodome separates hash construction from signing (`SHA1.new(data)` then `pkcs1_15.sign(hash_obj)`). The `cryptography` API combines them (`key.sign(data, padding, hash_algo)` — it hashes internally). For the two-step `sign_message` pattern (`SHA1.new(content).update(xmc)`), this is equivalent to `key.sign(content + xmc, ...)` because SHA1 is a Merkle–Damgård hash where `H(a).update(b) == H(a || b)`. The test proves byte-identical signatures.

3. **PBKDF2 PRF parameter**: `schema.py` uses `hmac_hash_module=Cryptodome.Hash.SHA256`, which is standard HMAC-SHA256 PRF — directly equivalent to `PBKDF2HMAC(algorithm=hashes.SHA256())`. If it had used the `prf=` parameter instead (which takes a custom lambda), the output would differ because PyCryptodome's `prf=` default is HMAC-SHA1. The test vectors confirmed that `hmac_hash_module=` is used and the outputs match.

---

## Improvement Opportunities

The migration doesn't just swap libraries — it can make the crypto code better:

1. **Explicit nonce handling**: The `nonce + b"\x00" * 8` pattern is self-documenting, unlike PyCryptodome's implicit zero-padding. Future readers see exactly what the 16-byte CTR IV looks like.

2. **RSA sign data flow clarity**: Concatenating `content + xmc` before signing makes the data flow obvious. The current two-step hash is correct but requires knowing SHA1's internal state model to verify.

3. **Padding strictness (optional)**: The manual PKCS7 unpad `data[:-data[-1]]` doesn't validate padding bytes. The `cryptography` library's `PKCS7` padding module does. Consider switching if you want stricter validation — but keep manual unpad if compatibility with potentially malformed ciphertext matters.
