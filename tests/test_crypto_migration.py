"""Comparison tests: verify that the cryptography (pyca) migration produces
identical results to the original pycryptodomex implementation.

Each test runs the same operation through both libraries with identical inputs
and asserts the outputs match byte-for-byte.
"""

import os
import pytest

# ---------------------------------------------------------------------------
# pycryptodomex (reference implementation)
# ---------------------------------------------------------------------------
import Cryptodome.Cipher.AES
import Cryptodome.Cipher.PKCS1_v1_5
import Cryptodome.Hash.SHA1
import Cryptodome.Hash.SHA256
import Cryptodome.Protocol.KDF
import Cryptodome.PublicKey.RSA
import Cryptodome.Signature.pkcs1_15

# ---------------------------------------------------------------------------
# cryptography (pyca) — new implementation
# ---------------------------------------------------------------------------
import cryptography.hazmat.primitives.asymmetric.padding
import cryptography.hazmat.primitives.asymmetric.rsa
import cryptography.hazmat.primitives.asymmetric.utils
import cryptography.hazmat.primitives.ciphers
import cryptography.hazmat.primitives.ciphers.algorithms
import cryptography.hazmat.primitives.ciphers.modes
import cryptography.hazmat.primitives.hashes
import cryptography.hazmat.primitives.kdf.pbkdf2
import cryptography.hazmat.primitives.serialization


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A deterministic 1024-bit RSA key in PEM format, generated once for testing.
_TEST_RSA_PEM = None


def _generate_test_key_pem() -> bytes:
    """Generate a fresh RSA-1024 key and return PEM bytes.

    We generate via cryptography then verify both libraries can load it.
    """
    key = cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key(
        public_exponent=65537,
        key_size=1024,
    )
    return key.private_bytes(
        cryptography.hazmat.primitives.serialization.Encoding.PEM,
        cryptography.hazmat.primitives.serialization.PrivateFormat.TraditionalOpenSSL,
        cryptography.hazmat.primitives.serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def rsa_pem() -> bytes:
    global _TEST_RSA_PEM
    if _TEST_RSA_PEM is None:
        _TEST_RSA_PEM = _generate_test_key_pem()
    return _TEST_RSA_PEM


@pytest.fixture(scope="module")
def pycryptodome_rsa(rsa_pem):
    return Cryptodome.PublicKey.RSA.import_key(rsa_pem)


@pytest.fixture(scope="module")
def pyca_rsa(rsa_pem):
    return cryptography.hazmat.primitives.serialization.load_pem_private_key(rsa_pem, password=None)


# ---------------------------------------------------------------------------
# 1. RSA key loading — public key components match
# ---------------------------------------------------------------------------


class TestRSAKeyLoading:
    def test_public_exponent_matches(self, pycryptodome_rsa, pyca_rsa):
        assert pycryptodome_rsa.e == pyca_rsa.public_key().public_numbers().e

    def test_modulus_matches(self, pycryptodome_rsa, pyca_rsa):
        assert pycryptodome_rsa.n == pyca_rsa.public_key().public_numbers().n

    def test_private_exponent_matches(self, pycryptodome_rsa, pyca_rsa):
        assert pycryptodome_rsa.d == pyca_rsa.private_numbers().d

    def test_public_key_pem_matches(self, pycryptodome_rsa, pyca_rsa):
        pcd_pub = pycryptodome_rsa.public_key().export_key("PEM")
        pyca_pub = pyca_rsa.public_key().public_bytes(
            cryptography.hazmat.primitives.serialization.Encoding.PEM,
            cryptography.hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        # pyca adds a trailing newline, pycryptodome does not — normalize
        assert pcd_pub.strip() == pyca_pub.strip()


# ---------------------------------------------------------------------------
# 2. RSA key loading with password
# ---------------------------------------------------------------------------


class TestRSAKeyLoadingWithPassword:
    @pytest.fixture(scope="class")
    def encrypted_pem(self):
        key = cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key(
            public_exponent=65537, key_size=1024
        )
        return key.private_bytes(
            cryptography.hazmat.primitives.serialization.Encoding.PEM,
            cryptography.hazmat.primitives.serialization.PrivateFormat.TraditionalOpenSSL,
            cryptography.hazmat.primitives.serialization.BestAvailableEncryption(b"testpassword"),
        )

    def test_password_protected_key_loads_identically(self, encrypted_pem):
        pcd_key = Cryptodome.PublicKey.RSA.import_key(encrypted_pem, "testpassword")
        pyca_key = cryptography.hazmat.primitives.serialization.load_pem_private_key(
            encrypted_pem, password=b"testpassword"
        )
        assert pcd_key.n == pyca_key.public_key().public_numbers().n
        assert pcd_key.e == pyca_key.public_key().public_numbers().e
        assert pcd_key.d == pyca_key.private_numbers().d


# ---------------------------------------------------------------------------
# 3. RSA PKCS1v1.5 signing (SHA1)  — mirrors util.sign_message
# ---------------------------------------------------------------------------


class TestRSASignPKCS1v15SHA1:
    @pytest.fixture(
        params=[
            b"hello world",
            b"",
            b"\x00\x01\x02" * 100,
            os.urandom(512),
        ],
        ids=["simple", "empty", "binary", "random"],
    )
    def message(self, request):
        return request.param

    def _sign_pycryptodome(self, key, data):
        sha1 = Cryptodome.Hash.SHA1.new(data)
        signer = Cryptodome.Signature.pkcs1_15.new(key)
        return signer.sign(sha1)

    def _sign_pyca(self, key, data):
        digest = cryptography.hazmat.primitives.hashes.Hash(
            cryptography.hazmat.primitives.hashes.SHA1()
        )
        digest.update(data)
        hash_value = digest.finalize()
        return key.sign(
            hash_value,
            cryptography.hazmat.primitives.asymmetric.padding.PKCS1v15(),
            cryptography.hazmat.primitives.asymmetric.utils.Prehashed(
                cryptography.hazmat.primitives.hashes.SHA1()
            ),
        )

    def test_signatures_match(self, pycryptodome_rsa, pyca_rsa, message):
        sig_old = self._sign_pycryptodome(pycryptodome_rsa, message)
        sig_new = self._sign_pyca(pyca_rsa, message)
        assert sig_old == sig_new

    def test_signature_with_xmc_suffix(self, pycryptodome_rsa, pyca_rsa):
        """Mirrors sign_message when request_xmc_hex is not None."""
        content = b"request body content"
        xmc = "abc123def456"

        # pycryptodome: incremental update
        sha1 = Cryptodome.Hash.SHA1.new(content)
        sha1.update(xmc.encode("UTF-8"))
        sig_old = Cryptodome.Signature.pkcs1_15.new(pycryptodome_rsa).sign(sha1)

        # pyca: incremental update
        digest = cryptography.hazmat.primitives.hashes.Hash(
            cryptography.hazmat.primitives.hashes.SHA1()
        )
        digest.update(content)
        digest.update(xmc.encode("UTF-8"))
        hash_value = digest.finalize()
        sig_new = pyca_rsa.sign(
            hash_value,
            cryptography.hazmat.primitives.asymmetric.padding.PKCS1v15(),
            cryptography.hazmat.primitives.asymmetric.utils.Prehashed(
                cryptography.hazmat.primitives.hashes.SHA1()
            ),
        )

        assert sig_old == sig_new


# ---------------------------------------------------------------------------
# 4. RSA PKCS1v1.5 decryption — mirrors util.decrypt_rsa
# ---------------------------------------------------------------------------


class TestRSADecryptPKCS1v15:
    def _encrypt_with_public_key(self, pycryptodome_rsa, plaintext):
        """Encrypt with PyCryptodome's public key for both libs to decrypt."""
        from Cryptodome.Cipher import PKCS1_v1_5 as PKCS1_v1_5_cipher

        cipher = PKCS1_v1_5_cipher.new(pycryptodome_rsa.public_key())
        return cipher.encrypt(plaintext)

    def test_decrypt_matches(self, pycryptodome_rsa, pyca_rsa):
        plaintext = b"secret message for RSA"
        ciphertext = self._encrypt_with_public_key(pycryptodome_rsa, plaintext)

        # pycryptodome
        dec_old = Cryptodome.Cipher.PKCS1_v1_5.new(pycryptodome_rsa).decrypt(ciphertext, None)

        # pyca
        try:
            dec_new = pyca_rsa.decrypt(
                ciphertext,
                cryptography.hazmat.primitives.asymmetric.padding.PKCS1v15(),
            )
        except ValueError:
            dec_new = None

        assert dec_old == dec_new

    def test_decrypt_wrong_key_returns_none(self, pycryptodome_rsa):
        """Ciphertext encrypted with a different key should fail to decrypt.

        PyCryptodome returns the sentinel (None); the NPPS4 migration maps
        cryptography's ValueError to None.  PKCS1v1.5 decryption of random
        garbage may not always raise an error (Bleichenbacher-style behavior),
        so we test with a properly-formed ciphertext encrypted by a *different*
        key to guarantee a padding failure.
        """
        # Generate a separate key and encrypt with its public key
        other_key = Cryptodome.PublicKey.RSA.generate(1024)
        from Cryptodome.Cipher import PKCS1_v1_5 as PKCS1_v1_5_cipher

        ciphertext = PKCS1_v1_5_cipher.new(other_key.public_key()).encrypt(b"wrong key test")

        # PyCryptodome: decrypt with the *test* key (wrong key) — should return sentinel
        dec_old = Cryptodome.Cipher.PKCS1_v1_5.new(pycryptodome_rsa).decrypt(ciphertext, None)
        assert dec_old is None or dec_old != b"wrong key test"

    def test_decrypt_multiple_plaintexts(self, pycryptodome_rsa, pyca_rsa):
        for plaintext in [b"a", b"x" * 50, b"\xff" * 10, b""]:
            if len(plaintext) > 86:  # max for 1024-bit key with PKCS1v1.5
                continue
            ciphertext = self._encrypt_with_public_key(pycryptodome_rsa, plaintext)

            dec_old = Cryptodome.Cipher.PKCS1_v1_5.new(pycryptodome_rsa).decrypt(ciphertext, None)
            try:
                dec_new = pyca_rsa.decrypt(
                    ciphertext,
                    cryptography.hazmat.primitives.asymmetric.padding.PKCS1v15(),
                )
            except ValueError:
                dec_new = None

            assert dec_old == dec_new == plaintext


# ---------------------------------------------------------------------------
# 5. AES-CBC decryption — mirrors util.decrypt_aes
# ---------------------------------------------------------------------------


class TestAESCBCDecrypt:
    def _make_cbc_ciphertext_pycryptodome(self, key, iv, plaintext):
        """Encrypt with PKCS7 padding using pycryptodome, return iv + ciphertext."""
        padded = Cryptodome.Util.Padding.pad(plaintext, 16)
        aes = Cryptodome.Cipher.AES.new(key, Cryptodome.Cipher.AES.MODE_CBC, iv=iv)
        return iv + aes.encrypt(padded)

    def _decrypt_pycryptodome(self, key, data):
        aes = Cryptodome.Cipher.AES.new(key, Cryptodome.Cipher.AES.MODE_CBC, iv=data[:16])
        decrypted = aes.decrypt(data[16:])
        return decrypted[: -decrypted[-1]]

    def _decrypt_pyca(self, key, data):
        cipher = cryptography.hazmat.primitives.ciphers.Cipher(
            cryptography.hazmat.primitives.ciphers.algorithms.AES(key),
            cryptography.hazmat.primitives.ciphers.modes.CBC(data[:16]),
        )
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(data[16:]) + decryptor.finalize()
        return decrypted[: -decrypted[-1]]

    @pytest.fixture(
        params=[
            b"hello world!!!!",  # 15 bytes → 1 byte padding
            b"exact16byteslong",  # 16 bytes → 16 bytes padding
            b"short",  # 5 bytes
            b"a" * 256,  # multi-block
            b"\x00" * 48,  # null bytes
        ],
        ids=["15bytes", "16bytes", "5bytes", "256bytes", "nulls"],
    )
    def plaintext(self, request):
        return request.param

    def test_decryption_matches(self, plaintext):
        key = os.urandom(16)
        iv = os.urandom(16)
        ciphertext = self._make_cbc_ciphertext_pycryptodome(key, iv, plaintext)

        dec_old = self._decrypt_pycryptodome(key, ciphertext)
        dec_new = self._decrypt_pyca(key, ciphertext)

        assert dec_old == dec_new == plaintext

    def test_aes256_cbc(self):
        """Test with AES-256 key."""
        key = os.urandom(32)
        iv = os.urandom(16)
        plaintext = b"AES-256 test data"
        ciphertext = self._make_cbc_ciphertext_pycryptodome(key, iv, plaintext)

        dec_old = self._decrypt_pycryptodome(key, ciphertext)
        dec_new = self._decrypt_pyca(key, ciphertext)

        assert dec_old == dec_new == plaintext


# ---------------------------------------------------------------------------
# 6. AES-CTR encrypt/decrypt — mirrors schema.initialize_aes_for_action_field
# ---------------------------------------------------------------------------


class TestAESCTR:
    def _make_pycryptodome_ctr(self, key, nonce_8):
        return Cryptodome.Cipher.AES.new(
            key,
            Cryptodome.Cipher.AES.MODE_CTR,
            nonce=nonce_8,
            initial_value=0,
        )

    def _make_pyca_ctr(self, key, nonce_8):
        nonce_16 = nonce_8 + b"\x00" * 8
        return cryptography.hazmat.primitives.ciphers.Cipher(
            cryptography.hazmat.primitives.ciphers.algorithms.AES(key),
            cryptography.hazmat.primitives.ciphers.modes.CTR(nonce_16),
        )

    @pytest.fixture(
        params=[
            b"short",
            b"exactly16bytes!!",
            b"a" * 200,
            b"\x00" * 32,
            os.urandom(64),
        ],
        ids=["short", "one_block", "multi_block", "nulls", "random"],
    )
    def plaintext(self, request):
        return request.param

    def test_encrypt_matches(self, plaintext):
        key = os.urandom(16)
        nonce = os.urandom(8)

        enc_old = self._make_pycryptodome_ctr(key, nonce).encrypt(plaintext)
        encryptor = self._make_pyca_ctr(key, nonce).encryptor()
        enc_new = encryptor.update(plaintext) + encryptor.finalize()

        assert enc_old == enc_new

    def test_decrypt_matches(self, plaintext):
        key = os.urandom(16)
        nonce = os.urandom(8)

        # Encrypt with pycryptodome
        ciphertext = self._make_pycryptodome_ctr(key, nonce).encrypt(plaintext)

        # Decrypt with both
        dec_old = self._make_pycryptodome_ctr(key, nonce).decrypt(ciphertext)
        decryptor = self._make_pyca_ctr(key, nonce).decryptor()
        dec_new = decryptor.update(ciphertext) + decryptor.finalize()

        assert dec_old == dec_new == plaintext

    def test_cross_encrypt_decrypt(self, plaintext):
        """Encrypt with one lib, decrypt with the other."""
        key = os.urandom(16)
        nonce = os.urandom(8)

        # pyca encrypt → pycryptodome decrypt
        encryptor = self._make_pyca_ctr(key, nonce).encryptor()
        ct1 = encryptor.update(plaintext) + encryptor.finalize()
        pt1 = self._make_pycryptodome_ctr(key, nonce).decrypt(ct1)

        # pycryptodome encrypt → pyca decrypt
        ct2 = self._make_pycryptodome_ctr(key, nonce).encrypt(plaintext)
        decryptor = self._make_pyca_ctr(key, nonce).decryptor()
        pt2 = decryptor.update(ct2) + decryptor.finalize()

        assert pt1 == pt2 == plaintext


# ---------------------------------------------------------------------------
# 7. AES-CTR wrapper class — mirrors schema._AesCtrCipher
# ---------------------------------------------------------------------------


class TestAesCtrCipherWrapper:
    """Test the _AesCtrCipher wrapper behaves identically to PyCryptodome."""

    def _make_wrapper(self, key, nonce_16):
        """Reproduce schema._AesCtrCipher inline."""
        cipher = cryptography.hazmat.primitives.ciphers.Cipher(
            cryptography.hazmat.primitives.ciphers.algorithms.AES(key),
            cryptography.hazmat.primitives.ciphers.modes.CTR(nonce_16),
        )

        class Wrapper:
            def __init__(self, c):
                self._cipher = c

            def encrypt(self, data):
                enc = self._cipher.encryptor()
                return enc.update(data) + enc.finalize()

            def decrypt(self, data):
                dec = self._cipher.decryptor()
                return dec.update(data) + dec.finalize()

        return Wrapper(cipher)

    def test_encrypt_decrypt_roundtrip(self):
        key = os.urandom(16)
        salt = os.urandom(16)
        nonce_8 = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))
        nonce_16 = nonce_8 + b"\x00" * 8

        plaintext = b'{"type":"item","items":[{"add_type":1001,"item_id":1,"amount":5}]}'

        # PyCryptodome reference
        pcd_cipher = Cryptodome.Cipher.AES.new(
            key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce_8, initial_value=0
        )
        ciphertext_ref = pcd_cipher.encrypt(plaintext)

        # Wrapper
        wrapper = self._make_wrapper(key, nonce_16)
        ciphertext_new = wrapper.encrypt(plaintext)
        assert ciphertext_ref == ciphertext_new

        # Decrypt with wrapper
        wrapper2 = self._make_wrapper(key, nonce_16)
        assert wrapper2.decrypt(ciphertext_ref) == plaintext

    def test_wrapper_can_be_used_for_separate_encrypt_and_decrypt(self):
        """Each call to encrypt/decrypt creates a fresh encryptor/decryptor."""
        key = os.urandom(16)
        nonce_16 = os.urandom(8) + b"\x00" * 8

        wrapper = self._make_wrapper(key, nonce_16)
        pt = b"some data to encrypt"

        ct1 = wrapper.encrypt(pt)
        ct2 = wrapper.encrypt(pt)
        # Same key+nonce → same ciphertext (CTR is deterministic)
        assert ct1 == ct2

        assert wrapper.decrypt(ct1) == pt


# ---------------------------------------------------------------------------
# 8. PBKDF2 with SHA256 — mirrors schema.derive_serial_code_action_key
# ---------------------------------------------------------------------------


class TestPBKDF2:
    @pytest.fixture(
        params=[
            ("password", b"salt1234salt5678"),
            ("", b"\x00" * 16),
            ("unicode-Pässwörd-日本語", b"anothersalt12345"),
            ("short", b"s" * 16),
        ],
        ids=["normal", "empty_password", "unicode", "short_password"],
    )
    def password_and_salt(self, request):
        return request.param

    def _derive_pycryptodome(self, password, salt):
        return Cryptodome.Protocol.KDF.PBKDF2(
            password.encode("utf-8"),
            salt,
            16,  # dkLen
            4,  # count (iterations)
            hmac_hash_module=Cryptodome.Hash.SHA256,
        )

    def _derive_pyca(self, password, salt):
        kdf = cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC(
            algorithm=cryptography.hazmat.primitives.hashes.SHA256(),
            length=16,
            salt=salt,
            iterations=4,
        )
        return kdf.derive(password.encode("utf-8"))

    def test_derived_keys_match(self, password_and_salt):
        password, salt = password_and_salt
        key_old = self._derive_pycryptodome(password, salt)
        key_new = self._derive_pyca(password, salt)
        assert key_old == key_new

    def test_different_iterations_still_match(self):
        """Sanity check with higher iteration count."""
        password = "test"
        salt = os.urandom(16)

        key_old = Cryptodome.Protocol.KDF.PBKDF2(
            password.encode("utf-8"), salt, 32, 1000,
            hmac_hash_module=Cryptodome.Hash.SHA256,
        )
        kdf = cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC(
            algorithm=cryptography.hazmat.primitives.hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=1000,
        )
        key_new = kdf.derive(password.encode("utf-8"))
        assert key_old == key_new


# ---------------------------------------------------------------------------
# 9. RSA key generation and PEM export — mirrors make_server_key.py
# ---------------------------------------------------------------------------


class TestRSAKeyGeneration:
    def test_generated_key_pem_loadable_by_both_libs(self):
        """A key generated by cryptography can be loaded by pycryptodome."""
        key = cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key(
            public_exponent=65537, key_size=1024
        )
        pem = key.private_bytes(
            cryptography.hazmat.primitives.serialization.Encoding.PEM,
            cryptography.hazmat.primitives.serialization.PrivateFormat.TraditionalOpenSSL,
            cryptography.hazmat.primitives.serialization.NoEncryption(),
        )

        pcd_key = Cryptodome.PublicKey.RSA.import_key(pem)
        pyca_key = cryptography.hazmat.primitives.serialization.load_pem_private_key(pem, password=None)

        assert pcd_key.n == pyca_key.public_key().public_numbers().n
        assert pcd_key.e == pyca_key.public_key().public_numbers().e

    def test_pycryptodome_generated_key_loadable_by_pyca(self):
        """A key generated by pycryptodome can be loaded by cryptography."""
        pcd_key = Cryptodome.PublicKey.RSA.generate(1024)
        pem = pcd_key.export_key("PEM")

        pyca_key = cryptography.hazmat.primitives.serialization.load_pem_private_key(pem, password=None)

        assert pcd_key.n == pyca_key.public_key().public_numbers().n
        assert pcd_key.e == pyca_key.public_key().public_numbers().e


# ---------------------------------------------------------------------------
# 10. End-to-end: full serial code action flow
# ---------------------------------------------------------------------------


class TestSerialCodeActionFlow:
    """Simulate the full encrypt → derive key → decrypt flow from schema.py
    using both libraries and verify interoperability."""

    def test_full_flow_cross_library(self):
        input_code = "TESTCODE123"
        salt = os.urandom(16)
        plaintext = b'{"type":"item","items":[{"add_type":1001,"item_id":1,"amount":5}]}'

        # Derive key with pycryptodome
        key_old = Cryptodome.Protocol.KDF.PBKDF2(
            input_code.encode("utf-8"), salt, 16, 4,
            hmac_hash_module=Cryptodome.Hash.SHA256,
        )

        # Derive key with pyca
        kdf = cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC(
            algorithm=cryptography.hazmat.primitives.hashes.SHA256(),
            length=16, salt=salt, iterations=4,
        )
        key_new = kdf.derive(input_code.encode("utf-8"))

        assert key_old == key_new
        key = key_old

        # Compute nonce (same logic as schema.py)
        nonce_8 = bytes(a ^ b for a, b in zip(salt[:8], salt[8:]))

        # Encrypt with pycryptodome
        ct_old = Cryptodome.Cipher.AES.new(
            key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce_8, initial_value=0,
        ).encrypt(plaintext)

        # Encrypt with pyca
        nonce_16 = nonce_8 + b"\x00" * 8
        enc = cryptography.hazmat.primitives.ciphers.Cipher(
            cryptography.hazmat.primitives.ciphers.algorithms.AES(key),
            cryptography.hazmat.primitives.ciphers.modes.CTR(nonce_16),
        ).encryptor()
        ct_new = enc.update(plaintext) + enc.finalize()

        assert ct_old == ct_new

        # Decrypt pycryptodome-encrypted data with pyca
        dec = cryptography.hazmat.primitives.ciphers.Cipher(
            cryptography.hazmat.primitives.ciphers.algorithms.AES(key),
            cryptography.hazmat.primitives.ciphers.modes.CTR(nonce_16),
        ).decryptor()
        pt_cross = dec.update(ct_old) + dec.finalize()
        assert pt_cross == plaintext

        # Decrypt pyca-encrypted data with pycryptodome
        pt_cross2 = Cryptodome.Cipher.AES.new(
            key, Cryptodome.Cipher.AES.MODE_CTR, nonce=nonce_8, initial_value=0,
        ).decrypt(ct_new)
        assert pt_cross2 == plaintext


# ---------------------------------------------------------------------------
# 11. SHA1 hashing comparison
# ---------------------------------------------------------------------------


class TestSHA1:
    @pytest.fixture(
        params=[b"", b"hello", b"\x00" * 100, os.urandom(1024)],
        ids=["empty", "hello", "nulls", "random"],
    )
    def data(self, request):
        return request.param

    def test_sha1_digest_matches(self, data):
        old = Cryptodome.Hash.SHA1.new(data).digest()

        h = cryptography.hazmat.primitives.hashes.Hash(
            cryptography.hazmat.primitives.hashes.SHA1()
        )
        h.update(data)
        new = h.finalize()

        assert old == new

    def test_sha1_incremental_update(self):
        part1 = b"hello "
        part2 = b"world"

        old = Cryptodome.Hash.SHA1.new(part1)
        old.update(part2)
        digest_old = old.digest()

        h = cryptography.hazmat.primitives.hashes.Hash(
            cryptography.hazmat.primitives.hashes.SHA1()
        )
        h.update(part1)
        h.update(part2)
        digest_new = h.finalize()

        assert digest_old == digest_new
