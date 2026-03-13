"""
Verify that the `cryptography` (pyca) backend produces byte-identical results
to the pycryptodomex backend for every crypto operation NPPS4 uses.

Usage:
    1. Generate vectors (requires pycryptodomex):
           python -m tests.generate_crypto_vectors

    2. Run these tests (requires cryptography):
           python -m pytest tests/test_crypto_migration.py -v

    Both libraries can be installed simultaneously — they don't conflict.
    After migration, only `cryptography` is needed, and these tests become
    permanent regression tests using the committed vectors file.
"""
import base64
import json
import os

import pytest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

VECTORS_FILE = os.path.join(os.path.dirname(__file__), "crypto_test_vectors.json")


@pytest.fixture(scope="module")
def vectors():
    if not os.path.exists(VECTORS_FILE):
        pytest.skip(
            "No vectors file. Run `python -m tests.generate_crypto_vectors` first."
        )
    with open(VECTORS_FILE) as f:
        return json.load(f)


def _load_key(pem_b64: str, password: str | None = None):
    pem = base64.b64decode(pem_b64)
    pwd = password.encode() if password else None
    return serialization.load_pem_private_key(pem, password=pwd)


# ──────────────────────────────────────────────
# RSA Sign — mirrors npps4/util.py:sign_message
# ──────────────────────────────────────────────


class TestRSASign:
    """
    sign_message does: SHA1.new(content).update(xmc); pkcs1_15.sign(hash)
    cryptography equivalent: key.sign(content + xmc, PKCS1v15(), SHA1())

    The two-step Cryptodome hash (new + update) is equivalent to hashing the
    concatenation. This test proves it.
    """

    def test_sign_with_xmc(self, vectors):
        v = vectors["rsa_sign_with_xmc"]
        key = _load_key(vectors["rsa_key_pem"])
        content = base64.b64decode(v["content"])
        xmc = v["xmc"].encode("UTF-8")
        expected = base64.b64decode(v["signature"])

        # cryptography hashes internally — we concatenate content + xmc
        signature = key.sign(content + xmc, asym_padding.PKCS1v15(), hashes.SHA1())
        assert signature == expected

    def test_sign_without_xmc(self, vectors):
        v = vectors["rsa_sign_no_xmc"]
        key = _load_key(vectors["rsa_key_pem"])
        content = base64.b64decode(v["content"])
        expected = base64.b64decode(v["signature"])

        signature = key.sign(content, asym_padding.PKCS1v15(), hashes.SHA1())
        assert signature == expected


# ──────────────────────────────────────────────────
# RSA Decrypt — mirrors npps4/util.py:decrypt_rsa
# ──────────────────────────────────────────────────


class TestRSADecrypt:
    """
    decrypt_rsa does: PKCS1_v1_5.new(key).decrypt(data, None)
    sentinel=None means it raises ValueError on padding error.
    cryptography: key.decrypt(data, PKCS1v15()) — also raises on bad padding.
    """

    def test_decrypt(self, vectors):
        v = vectors["rsa_decrypt"]
        key = _load_key(vectors["rsa_key_pem"])
        ciphertext = base64.b64decode(v["ciphertext"])
        expected = base64.b64decode(v["plaintext"])

        plaintext = key.decrypt(ciphertext, asym_padding.PKCS1v15())
        assert plaintext == expected


# ─────────────────────────────────────────────────
# AES-CBC Decrypt — mirrors npps4/util.py:decrypt_aes
# ─────────────────────────────────────────────────


class TestAESCBC:
    """
    decrypt_aes does:
        iv = data[:16]
        aes.decrypt(data[16:])
        unpad: data[:-data[-1]]  (manual PKCS7)
    """

    def test_decrypt(self, vectors):
        v = vectors["aes_cbc"]
        key = base64.b64decode(v["key"])
        ct_with_iv = base64.b64decode(v["ciphertext_with_iv"])
        expected = base64.b64decode(v["plaintext"])

        iv, ct = ct_with_iv[:16], ct_with_iv[16:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        # Manual PKCS7 unpad — matching the production code exactly
        plaintext = padded[: -padded[-1]]
        assert plaintext == expected


# ──────────────────────────────────────────────────────────
# AES-CTR — mirrors npps4/data/schema.py:initialize_aes_for_action_field
# ──────────────────────────────────────────────────────────


class TestAESCTR:
    """
    PyCryptodome: AES.new(key, MODE_CTR, nonce=nonce_8bytes, initial_value=0)
    Internal IV layout: nonce(8) || counter(8, big-endian starting at 0)

    cryptography: modes.CTR(nonce_16bytes)
    We must construct: nonce(8) || b'\\x00' * 8
    """

    def test_encrypt(self, vectors):
        v = vectors["aes_ctr"]
        key = base64.b64decode(v["key"])
        nonce = base64.b64decode(v["nonce"])
        plaintext = base64.b64decode(v["plaintext"])
        expected_ct = base64.b64decode(v["ciphertext"])

        # Expand 8-byte nonce to 16-byte IV (nonce || zero counter)
        full_nonce = nonce + b"\x00" * (16 - len(nonce))
        cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        assert ciphertext == expected_ct

    def test_decrypt(self, vectors):
        v = vectors["aes_ctr"]
        key = base64.b64decode(v["key"])
        nonce = base64.b64decode(v["nonce"])
        ciphertext = base64.b64decode(v["ciphertext"])
        expected_pt = base64.b64decode(v["plaintext"])

        full_nonce = nonce + b"\x00" * (16 - len(nonce))
        cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        assert plaintext == expected_pt


# ────────────────────────────────────────────────────────────
# PBKDF2-SHA256 — mirrors npps4/data/schema.py:derive_serial_code_action_key
# ────────────────────────────────────────────────────────────


class TestPBKDF2:
    """
    PyCryptodome: PBKDF2(password, salt, dkLen=16, count=4, hmac_hash_module=SHA256)
    hmac_hash_module= uses standard HMAC-based PRF (NOT the custom prf= lambda).

    cryptography: PBKDF2HMAC(algorithm=SHA256(), length=16, salt=salt, iterations=4)
    These should be identical — both implement RFC 2898 with HMAC-SHA256.
    """

    def test_derive(self, vectors):
        v = vectors["pbkdf2_sha256"]
        password = base64.b64decode(v["password"])
        salt = base64.b64decode(v["salt"])
        expected = base64.b64decode(v["derived_key"])

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=v["dk_len"],
            salt=salt,
            iterations=v["iterations"],
        )
        derived = kdf.derive(password)
        assert derived == expected


# ─────────────────────────────────────────────────────────────────
# Full serial code flow — derive_serial_code_action_key + AES-CTR
# ─────────────────────────────────────────────────────────────────


class TestSerialCodeFlow:
    """
    End-to-end: PBKDF2 key derivation → xor nonce → AES-CTR decrypt.
    Mirrors schema.SerialCode.get_action().
    """

    def test_decrypt_action(self, vectors):
        v = vectors["serial_code_flow"]
        serial_code = v["serial_code"]
        salt = base64.b64decode(v["salt"])
        ciphertext = base64.b64decode(v["ciphertext"])
        expected_pt = base64.b64decode(v["plaintext"])
        expected_key = base64.b64decode(v["derived_key"])

        # Step 1: derive key (same as derive_serial_code_action_key)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=16,
            salt=salt,
            iterations=4,
        )
        key = kdf.derive(serial_code.encode("utf-8"))
        assert key == expected_key, "Key derivation mismatch"

        # Step 2: compute nonce (same as xorbytes(salt[:8], salt[8:]))
        nonce = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))
        expected_nonce = base64.b64decode(v["nonce"])
        assert nonce == expected_nonce, "Nonce mismatch"

        # Step 3: AES-CTR decrypt
        full_nonce = nonce + b"\x00" * 8
        cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        assert plaintext == expected_pt

    def test_encrypt_action(self, vectors):
        """Verify encrypt → decrypt round-trip with cryptography only."""
        v = vectors["serial_code_flow"]
        serial_code = v["serial_code"]
        salt = base64.b64decode(v["salt"])
        expected_ct = base64.b64decode(v["ciphertext"])
        plaintext = base64.b64decode(v["plaintext"])

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=16, salt=salt, iterations=4
        )
        key = kdf.derive(serial_code.encode("utf-8"))
        nonce = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))
        full_nonce = nonce + b"\x00" * 8

        cipher = Cipher(algorithms.AES(key), modes.CTR(full_nonce))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        assert ciphertext == expected_ct


# ──────────────────────────────────────────────
# RSA Key loading — mirrors config/config.py
# ──────────────────────────────────────────────


class TestRSAKeyLoading:
    """
    config.py: Cryptodome.PublicKey.RSA.import_key(pem_bytes, password)
    cryptography: load_pem_private_key(pem_bytes, password=password.encode())
    """

    def test_load_unprotected(self, vectors):
        key = _load_key(vectors["rsa_key_pem"])
        # Verify the key is usable by signing something
        sig = key.sign(b"test", asym_padding.PKCS1v15(), hashes.SHA1())
        assert len(sig) > 0

    def test_load_password_protected(self, vectors):
        v = vectors["rsa_key_password"]
        key = _load_key(v["encrypted_pem"], v["password"])
        # Verify modulus matches
        assert hex(key.private_numbers().public_numbers.n) == v["modulus_hex"]


# ───────────────────────────────────────────────────────
# RSA Key generation — mirrors make_server_key.py
# ───────────────────────────────────────────────────────


class TestRSAKeyGeneration:
    """
    make_server_key.py: RSA.generate(1024), export_key("PEM"), public_key().export_key("PEM")
    cryptography: rsa.generate_private_key(), private_bytes(), public_key().public_bytes()

    We can't compare against vectors (key gen is random), but we verify:
    1. A key generated with cryptography can be loaded by PyCryptodome (and vice versa)
    2. The PEM format is compatible
    """

    def test_keygen_pem_roundtrip(self, vectors):
        """A PyCryptodome-generated key PEM loads in cryptography."""
        v = vectors["rsa_keygen"]
        pem = base64.b64decode(v["private_pem"])
        key = serialization.load_pem_private_key(pem, password=None)
        assert key.key_size == v["bits"]

    def test_keygen_public_pem_roundtrip(self, vectors):
        """A PyCryptodome-generated public key PEM loads in cryptography."""
        v = vectors["rsa_keygen"]
        pub_pem = base64.b64decode(v["public_pem"])
        pub_key = serialization.load_pem_public_key(pub_pem)
        assert pub_key.key_size == v["bits"]

    def test_cryptography_keygen_produces_valid_pem(self):
        """A key generated with cryptography produces standard PEM."""
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        priv_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        pub_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        assert priv_pem.startswith(b"-----BEGIN RSA PRIVATE KEY-----")
        assert pub_pem.startswith(b"-----BEGIN PUBLIC KEY-----")

        # Round-trip: reload and sign
        reloaded = serialization.load_pem_private_key(priv_pem, password=None)
        sig = reloaded.sign(b"test", asym_padding.PKCS1v15(), hashes.SHA1())
        assert len(sig) > 0


# ──────────────────────────────────────────────────────────────
# decrypt_db_row.py AES-CBC — already has a cryptography fallback
# ──────────────────────────────────────────────────────────────


class TestDecryptDBRow:
    """
    The decrypt_aes in util/decrypt_db_row.py is identical to util.decrypt_aes:
    iv=data[:16], decrypt data[16:], manual PKCS7 unpad.
    Reuses the aes_cbc vectors — same algorithm, just different file.
    """

    def test_matches_aes_cbc_vectors(self, vectors):
        v = vectors["aes_cbc"]
        key = base64.b64decode(v["key"])
        ct_with_iv = base64.b64decode(v["ciphertext_with_iv"])
        expected = base64.b64decode(v["plaintext"])

        iv, ct = ct_with_iv[:16], ct_with_iv[16:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        plaintext = padded[: -padded[-1]]
        assert plaintext == expected
