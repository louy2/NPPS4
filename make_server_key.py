import os
import sys

import cryptography.hazmat.primitives.asymmetric.rsa
import cryptography.hazmat.primitives.serialization


def ask_confirm(prompt: str):
    while True:
        confirm = input(f"{prompt} [y/n] ")
        confirm_lower = confirm.lower()
        if confirm_lower == "y":
            return True
        elif confirm_lower == "n":
            return False
        else:
            print("Please type `y' or `n'!")


def print_public_key(key):
    pub_pem = key.public_key().public_bytes(
        cryptography.hazmat.primitives.serialization.Encoding.PEM,
        cryptography.hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    print(str(pub_pem, "UTF-8"))


if os.path.exists("server_key.pem"):
    with open("server_key.pem", "rb") as f:
        key = cryptography.hazmat.primitives.serialization.load_pem_private_key(f.read(), password=None)
        print_public_key(key)
    if "-p" in sys.argv:
        raise SystemExit(0)
    if not ask_confirm("WARNING: server_key.pem already exist. Overwrite?"):
        print("Key not overwritten")
        raise SystemExit(0)
    # Ask user again to make sure
    if not ask_confirm("WARNING WARNING: YOU HAVE BEEN WARNED! ARE YOU SURE? THE KEY WILL BE OVERWRITTEN!!!"):
        print("Key not overwritten")
        raise SystemExit(0)

key = cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key(public_exponent=65537, key_size=1024)
with open("server_key.pem", "wb") as f:
    f.write(key.private_bytes(
        cryptography.hazmat.primitives.serialization.Encoding.PEM,
        cryptography.hazmat.primitives.serialization.PrivateFormat.TraditionalOpenSSL,
        cryptography.hazmat.primitives.serialization.NoEncryption(),
    ))

print_public_key(key)
