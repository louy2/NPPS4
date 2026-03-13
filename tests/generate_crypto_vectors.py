#!/usr/bin/env python3
"""
Generate crypto test vectors from the CURRENT pycryptodomex implementation.

Run this ONCE before migration to capture ground-truth outputs:

    python -m tests.generate_crypto_vectors

Produces tests/crypto_test_vectors.json — the oracle for test_crypto_migration.py.
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

# Deterministic test inputs (NOT secrets — safe to commit).
TEST_RSA_KEY_PEM = b"""\
-----BEGIN RSA PRIVATE KEY-----
MIICWwIBAAKBgQCIZ99q8MmGix5cWV6XCFo8KmcxXgvWTzH5ewz/6kK7tt0H+XOm
4RAxmSikdOWPvyT6h2MtI+roLPXRFr9mCyS6Yh47VbWcStklqZqGTOeK4QYjVoZd
bCJcMopNztTpw9LMamquAo+poEdkvXghLo95Ct6pqhOv0W2Yc1ohYyQ56QIDAQAB
AoGACVZOPLsDmc4wk22PqW1/hcJOTYVh8Ix7v9eB4zZf1TXLfqtUlL4FC9bE1DBn
SAtzcSMZhsJrEZ5a65zabausxWwbg0S95YJwNEGggiAJPcvCYqiR2ePCBg0wZiNi
3fMpCQOz98Mbp6ap0gZcO5SjBCphL/w2Hwnnot2HFyvYIT0CQQC2SnkMOad9p9Fy
TbDbLaejQxDTcc5tWI5G7tlIPccDaMG3B8dzASgTAmdOUDUPO3ThiVoQYgQ5Dmt7
3e+G7wplAkEAv4+tcZPVUgToH/RuDHxKWUzKPcYcOwfOqNktLYGbkSQkGamp5pTS
HpaMpzjkpkXSsRTEqVaPiCVOMq2/21gXNQJAMatPGj6nXXyZfByhIMdq0vhWIFb1
GSQ0+CzidWWn0Uz842MyPCrHgY55GYSPQIxBx6ZGLQqX/ffo34JUXp7JZQJAPZnj
ibmjiMuhJd2Boiw58HucMb9KhsUc9PlZ6N9b+pGntkT0KP1EkKeTNZc7GCkt9toZ
3+bBI2PzwKJVJyEt3QJAa4W8rKndxwoCXA92oQZZywUuJc8m6WVafX18XHypmg8U
LnC4981qcZ9f6Zr5g1eWyWBB4BUe3N+gPn8GtrAMnQ==
-----END RSA PRIVATE KEY-----"""


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def collect_vectors() -> dict:
    vectors: dict = {}
    key = Cryptodome.PublicKey.RSA.import_key(TEST_RSA_KEY_PEM)
    vectors["rsa_key_pem"] = b64(TEST_RSA_KEY_PEM)

    # --- RSA Key Generation round-trip ---
    # Verify that a generated key can be exported and re-imported.
    gen_key = Cryptodome.PublicKey.RSA.generate(1024)
    gen_pem = gen_key.export_key("PEM")
    gen_pub_pem = gen_key.public_key().export_key("PEM")
    vectors["rsa_keygen"] = {
        "private_pem": b64(gen_pem),
        "public_pem": b64(gen_pub_pem),
        "bits": gen_key.size_in_bits(),
    }

    # --- RSA Sign (SHA1 + PKCS1v1.5) — matching util.sign_message ---
    # sign_message hashes in two steps: SHA1.new(content).update(xmc)
    # This is equivalent to SHA1(content || xmc).
    content = b'{"response_data":{},"status_code":200}'
    xmc = "abc123deadbeef"
    sha1 = Cryptodome.Hash.SHA1.new(content)
    sha1.update(xmc.encode("UTF-8"))
    signer = Cryptodome.Signature.pkcs1_15.new(key)
    signature = signer.sign(sha1)
    vectors["rsa_sign_with_xmc"] = {
        "content": b64(content),
        "xmc": xmc,
        "signature": b64(signature),
    }

    # sign_message without xmc (xmc=None path)
    sha1_no_xmc = Cryptodome.Hash.SHA1.new(content)
    signature_no_xmc = signer.sign(sha1_no_xmc)
    vectors["rsa_sign_no_xmc"] = {
        "content": b64(content),
        "signature": b64(signature_no_xmc),
    }

    # --- RSA Decrypt (PKCS1v1.5) — matching util.decrypt_rsa ---
    plaintext = b"session_key_here"
    encryptor = Cryptodome.Cipher.PKCS1_v1_5.new(key.public_key())
    # PKCS1v1.5 encryption is randomized, so we encrypt and record ciphertext.
    ciphertext = encryptor.encrypt(plaintext)
    vectors["rsa_decrypt"] = {
        "ciphertext": b64(ciphertext),
        "plaintext": b64(plaintext),
    }

    # --- AES-CBC Decrypt — matching util.decrypt_aes ---
    # decrypt_aes: iv = data[:16], decrypt data[16:], manual PKCS7 unpad data[:-data[-1]]
    aes_key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    iv = bytes.fromhex("10111213141516171819101b1c1d1e1f")
    aes_plaintext = b"hello AES-CBC!!\x00\x00"  # 18 bytes → pads to 32
    padded = Cryptodome.Util.Padding.pad(aes_plaintext, 16)
    aes_obj = Cryptodome.Cipher.AES.new(aes_key, Cryptodome.Cipher.AES.MODE_CBC, iv=iv)
    aes_ciphertext = iv + aes_obj.encrypt(padded)
    vectors["aes_cbc"] = {
        "key": b64(aes_key),
        "ciphertext_with_iv": b64(aes_ciphertext),
        "plaintext": b64(aes_plaintext),
    }

    # --- AES-CTR — matching schema.initialize_aes_for_action_field ---
    # Uses nonce= (8 bytes) with initial_value=0.
    # PyCryptodome: AES.new(key, MODE_CTR, nonce=nonce, initial_value=0)
    # This means the 16-byte IV is nonce(8) || counter(8, big-endian starting at 0).
    ctr_key = bytes.fromhex("aabbccddeeff00112233445566778899")
    ctr_nonce = bytes.fromhex("0102030405060708")  # 8 bytes, like xorbytes(salt[:8], salt[8:])
    ctr_plaintext = b'{"type":"item","items":[{"add_type":1001,"item_id":1,"amount":5}]}'
    aes_ctr = Cryptodome.Cipher.AES.new(ctr_key, Cryptodome.Cipher.AES.MODE_CTR, nonce=ctr_nonce, initial_value=0)
    ctr_ciphertext = aes_ctr.encrypt(ctr_plaintext)
    # Also verify decrypt
    aes_ctr2 = Cryptodome.Cipher.AES.new(ctr_key, Cryptodome.Cipher.AES.MODE_CTR, nonce=ctr_nonce, initial_value=0)
    assert aes_ctr2.decrypt(ctr_ciphertext) == ctr_plaintext
    vectors["aes_ctr"] = {
        "key": b64(ctr_key),
        "nonce": b64(ctr_nonce),
        "plaintext": b64(ctr_plaintext),
        "ciphertext": b64(ctr_ciphertext),
    }

    # --- PBKDF2-SHA256 — matching schema.derive_serial_code_action_key ---
    # PBKDF2(password, salt, dkLen=16, count=4, hmac_hash_module=SHA256)
    # hmac_hash_module= means standard HMAC-based PBKDF2 with SHA256.
    pbkdf2_password = "SERIAL-CODE-123".encode("utf-8")
    pbkdf2_salt = bytes.fromhex("deadbeefcafebabe1234567890abcdef")
    derived = Cryptodome.Protocol.KDF.PBKDF2(
        pbkdf2_password,
        pbkdf2_salt,
        16,
        4,
        hmac_hash_module=Cryptodome.Hash.SHA256,
    )
    vectors["pbkdf2_sha256"] = {
        "password": b64(pbkdf2_password),
        "salt": b64(pbkdf2_salt),
        "iterations": 4,
        "dk_len": 16,
        "derived_key": b64(derived),
    }

    # --- Full serial code flow ---
    # Exercises derive_serial_code_action_key + initialize_aes_for_action_field together.
    serial_code = "TESTCODE42"
    serial_salt = bytes.fromhex("aabbccddeeff00112233445566778899")  # 16 bytes
    sc_key = Cryptodome.Protocol.KDF.PBKDF2(
        serial_code.encode("utf-8"),
        serial_salt,
        16,
        4,
        hmac_hash_module=Cryptodome.Hash.SHA256,
    )
    sc_nonce = bytes(a ^ b for a, b in zip(serial_salt[:8], serial_salt[8:]))
    sc_aes = Cryptodome.Cipher.AES.new(sc_key, Cryptodome.Cipher.AES.MODE_CTR, nonce=sc_nonce, initial_value=0)
    sc_plaintext = b'{"type":"item","message_en":"Reward","message_jp":"Reward","items":[{"add_type":1001,"item_id":1,"amount":10}]}'
    sc_ciphertext = sc_aes.encrypt(sc_plaintext)
    vectors["serial_code_flow"] = {
        "serial_code": serial_code,
        "salt": b64(serial_salt),
        "derived_key": b64(sc_key),
        "nonce": b64(sc_nonce),
        "plaintext": b64(sc_plaintext),
        "ciphertext": b64(sc_ciphertext),
    }

    # --- RSA Key loading with password ---
    pw_key = Cryptodome.PublicKey.RSA.generate(1024)
    pw_pem = pw_key.export_key("PEM", passphrase="testpassword")
    reloaded = Cryptodome.PublicKey.RSA.import_key(pw_pem, "testpassword")
    assert reloaded.n == pw_key.n
    vectors["rsa_key_password"] = {
        "encrypted_pem": b64(pw_pem),
        "password": "testpassword",
        "modulus_hex": hex(pw_key.n),
    }

    return vectors


def main():
    vectors = collect_vectors()
    with open(VECTORS_FILE, "w") as f:
        json.dump(vectors, f, indent=2)
    print(f"Saved {len(vectors)} vector groups to {VECTORS_FILE}")


if __name__ == "__main__":
    main()
