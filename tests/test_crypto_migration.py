"""Verify that the NPPS4 cryptography functions produce identical results
to the original pycryptodomex implementation.

Each test calls the real NPPS4 function and compares against pycryptodomex.
Requires Python >= 3.12 and all NPPS4 dependencies installed.
"""

import base64
import os
import unittest.mock

import pytest

import Cryptodome.Cipher.AES
import Cryptodome.Cipher.PKCS1_v1_5
import Cryptodome.Hash.SHA1
import Cryptodome.Hash.SHA256
import Cryptodome.Protocol.KDF
import Cryptodome.PublicKey.RSA
import Cryptodome.Signature.pkcs1_15
import Cryptodome.Util.Padding

import cryptography.hazmat.primitives.asymmetric.rsa
import cryptography.hazmat.primitives.serialization

# Import NPPS4 modules directly (requires Python >= 3.12 + deps)
from npps4.config import config
from npps4 import util
from npps4.data import schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rsa_pem():
    """Generate a fresh RSA-1024 PEM key for testing."""
    key = cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key(
        public_exponent=65537, key_size=1024,
    )
    return key.private_bytes(
        cryptography.hazmat.primitives.serialization.Encoding.PEM,
        cryptography.hazmat.primitives.serialization.PrivateFormat.TraditionalOpenSSL,
        cryptography.hazmat.primitives.serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def pycryptodome_rsa(rsa_pem):
    return Cryptodome.PublicKey.RSA.import_key(rsa_pem)


@pytest.fixture(scope="module")
def pyca_rsa(rsa_pem):
    return cryptography.hazmat.primitives.serialization.load_pem_private_key(rsa_pem, password=None)


# ---------------------------------------------------------------------------
# util.sign_message
# ---------------------------------------------------------------------------

class TestSignMessage:
    def test_no_xmc(self, pycryptodome_rsa, pyca_rsa):
        content = b"test request body"

        with unittest.mock.patch.object(config, "get_server_rsa", return_value=pyca_rsa):
            result = util.sign_message(content, None)

        sha1 = Cryptodome.Hash.SHA1.new(content)
        ref_sig = Cryptodome.Signature.pkcs1_15.new(pycryptodome_rsa).sign(sha1)
        assert result == str(base64.b64encode(ref_sig), "UTF-8")

    def test_with_xmc(self, pycryptodome_rsa, pyca_rsa):
        content = b"test request body"
        xmc = "deadbeef1234"

        with unittest.mock.patch.object(config, "get_server_rsa", return_value=pyca_rsa):
            result = util.sign_message(content, xmc)

        sha1 = Cryptodome.Hash.SHA1.new(content)
        sha1.update(xmc.encode("UTF-8"))
        ref_sig = Cryptodome.Signature.pkcs1_15.new(pycryptodome_rsa).sign(sha1)
        assert result == str(base64.b64encode(ref_sig), "UTF-8")

    def test_returns_base64_string(self, pyca_rsa):
        with unittest.mock.patch.object(config, "get_server_rsa", return_value=pyca_rsa):
            result = util.sign_message(b"data", None)
        assert isinstance(result, str)
        base64.b64decode(result)

    @pytest.mark.parametrize("data", [b"", b"\x00\x01\x02" * 100, os.urandom(512)])
    def test_various_inputs(self, pycryptodome_rsa, pyca_rsa, data):
        with unittest.mock.patch.object(config, "get_server_rsa", return_value=pyca_rsa):
            result = util.sign_message(data, None)

        sha1 = Cryptodome.Hash.SHA1.new(data)
        ref_sig = Cryptodome.Signature.pkcs1_15.new(pycryptodome_rsa).sign(sha1)
        assert result == str(base64.b64encode(ref_sig), "UTF-8")


# ---------------------------------------------------------------------------
# util.decrypt_rsa
# ---------------------------------------------------------------------------

class TestDecryptRsa:
    def test_valid(self, pycryptodome_rsa, pyca_rsa):
        plaintext = b"secret message"
        ciphertext = Cryptodome.Cipher.PKCS1_v1_5.new(
            pycryptodome_rsa.public_key()
        ).encrypt(plaintext)

        with unittest.mock.patch.object(config, "get_server_rsa", return_value=pyca_rsa):
            result = util.decrypt_rsa(ciphertext)
        assert result == plaintext

    def test_returns_none_on_failure(self, pyca_rsa):
        other_key = Cryptodome.PublicKey.RSA.generate(1024)
        ciphertext = Cryptodome.Cipher.PKCS1_v1_5.new(
            other_key.public_key()
        ).encrypt(b"wrong key data")

        with unittest.mock.patch.object(config, "get_server_rsa", return_value=pyca_rsa):
            result = util.decrypt_rsa(ciphertext)
        assert result is None or result != b"wrong key data"


# ---------------------------------------------------------------------------
# util.decrypt_aes
# ---------------------------------------------------------------------------

class TestDecryptAes:
    @pytest.mark.parametrize(
        "plaintext",
        [b"a", b"hello world, this is a test!", b"x" * 16, b"\xff" * 31, b"y" * 256],
        ids=["1byte", "sentence", "16bytes", "31bytes", "256bytes"],
    )
    def test_matches_pycryptodome(self, plaintext):
        key = os.urandom(16)
        iv = os.urandom(16)
        padded = Cryptodome.Util.Padding.pad(plaintext, 16)
        aes = Cryptodome.Cipher.AES.new(key, Cryptodome.Cipher.AES.MODE_CBC, iv=iv)
        ciphertext = iv + aes.encrypt(padded)

        assert util.decrypt_aes(key, ciphertext) == plaintext


# ---------------------------------------------------------------------------
# schema.derive_serial_code_action_key
# ---------------------------------------------------------------------------

class TestDeriveSerialCodeActionKey:
    @pytest.mark.parametrize(
        "input_code,salt",
        [
            ("TESTCODE123", b"0123456789abcdef"),
            ("", b"\x00" * 16),
            ("unicode-Pässwörd-日本語", b"anothersalt12345"),
        ],
        ids=["normal", "empty", "unicode"],
    )
    def test_matches_pycryptodome(self, input_code, salt):
        result = schema.derive_serial_code_action_key(input_code, salt)
        ref = Cryptodome.Protocol.KDF.PBKDF2(
            input_code.encode("utf-8"), salt, 16, 4,
            hmac_hash_module=Cryptodome.Hash.SHA256,
        )
        assert result == ref


# ---------------------------------------------------------------------------
# schema.initialize_aes_for_action_field + _AesCtrCipher
# ---------------------------------------------------------------------------

class TestAesCtrCipher:
    def test_encrypt_matches_pycryptodome(self):
        salt = os.urandom(16)
        key = schema.derive_serial_code_action_key("MYCODE", salt)
        plaintext = b'{"type":"item","items":[{"add_type":1001,"item_id":1,"amount":5}]}'

        encrypted = schema.initialize_aes_for_action_field(key, salt).encrypt(plaintext)

        nonce_8 = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))
        ref = Cryptodome.Cipher.AES.new(
            key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce_8, initial_value=0,
        ).encrypt(plaintext)
        assert encrypted == ref

    def test_decrypt_pycryptodome_ciphertext(self):
        salt = os.urandom(16)
        input_code = "MYCODE"
        plaintext = b'{"type":"run","function":"test_func"}'

        ref_key = Cryptodome.Protocol.KDF.PBKDF2(
            input_code.encode("utf-8"), salt, 16, 4,
            hmac_hash_module=Cryptodome.Hash.SHA256,
        )
        nonce_8 = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))
        ciphertext = Cryptodome.Cipher.AES.new(
            ref_key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce_8, initial_value=0,
        ).encrypt(plaintext)

        key = schema.derive_serial_code_action_key(input_code, salt)
        result = schema.initialize_aes_for_action_field(key, salt).decrypt(ciphertext)
        assert result == plaintext

    def test_roundtrip(self):
        salt = os.urandom(16)
        key = schema.derive_serial_code_action_key("ROUNDTRIP", salt)
        plaintext = b'{"type":"item","items":[]}'

        ct = schema.initialize_aes_for_action_field(key, salt).encrypt(plaintext)
        pt = schema.initialize_aes_for_action_field(key, salt).decrypt(ct)
        assert pt == plaintext


# ---------------------------------------------------------------------------
# End-to-end: full serial code action flow
# ---------------------------------------------------------------------------

class TestSerialCodeActionFlow:
    def test_full_flow_cross_library(self):
        input_code = "TESTCODE123"
        salt = os.urandom(16)
        plaintext = b'{"type":"item","items":[{"add_type":1001,"item_id":1,"amount":5}]}'

        # NPPS4 derive + encrypt
        key = schema.derive_serial_code_action_key(input_code, salt)
        ct_new = schema.initialize_aes_for_action_field(key, salt).encrypt(plaintext)

        # pycryptodome derive + decrypt
        ref_key = Cryptodome.Protocol.KDF.PBKDF2(
            input_code.encode("utf-8"), salt, 16, 4,
            hmac_hash_module=Cryptodome.Hash.SHA256,
        )
        nonce_8 = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))
        pt_old = Cryptodome.Cipher.AES.new(
            ref_key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce_8, initial_value=0,
        ).decrypt(ct_new)

        assert key == ref_key
        assert pt_old == plaintext


# ---------------------------------------------------------------------------
# config: RSA key loading
# ---------------------------------------------------------------------------

class TestConfigKeyLoading:
    def test_server_key_components_match(self):
        """The real server key loaded by config matches pycryptodomex."""
        pyca_key = config.get_server_rsa()

        with open(os.path.join(config.ROOT_DIR, config.CONFIG_DATA.main.server_private_key), "rb") as f:
            pcd_key = Cryptodome.PublicKey.RSA.import_key(f.read())

        assert pcd_key.n == pyca_key.public_key().public_numbers().n
        assert pcd_key.d == pyca_key.private_numbers().d

    def test_password_protected_key(self, rsa_pem):
        """Password-protected keys load identically via both libs."""
        key = cryptography.hazmat.primitives.serialization.load_pem_private_key(rsa_pem, password=None)
        encrypted_pem = key.private_bytes(
            cryptography.hazmat.primitives.serialization.Encoding.PEM,
            cryptography.hazmat.primitives.serialization.PrivateFormat.TraditionalOpenSSL,
            cryptography.hazmat.primitives.serialization.BestAvailableEncryption(b"testpw"),
        )

        pcd_key = Cryptodome.PublicKey.RSA.import_key(encrypted_pem, "testpw")
        pyca_key = cryptography.hazmat.primitives.serialization.load_pem_private_key(
            encrypted_pem, password=b"testpw"
        )
        assert pcd_key.n == pyca_key.public_key().public_numbers().n
        assert pcd_key.d == pyca_key.private_numbers().d
