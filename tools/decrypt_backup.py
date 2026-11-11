"""Turn an encrypted limefx backup (limefx-YYYY-MM-DD.db.enc, as sent to Telegram) back into a database file.

    pip install cryptography
    python decrypt_backup.py limefx-2026-11-11.db.enc

Asks for the backup password (the PT_BACKUP_PASSWORD value) and writes limefx-2026-11-11.db next to the input.
"""
import getpass
import gzip
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


def decrypt(blob: bytes, password: str) -> bytes:
    if blob[:5] != b"LFXB1":
        raise SystemExit("Not a limefx encrypted backup")
    salt, nonce, data = blob[5:21], blob[21:33], blob[33:]
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode())
    return gzip.decompress(AESGCM(key).decrypt(nonce, data, b"LFXB1"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1])
    try:
        raw = decrypt(src.read_bytes(), getpass.getpass("Backup password: "))
    except Exception:
        raise SystemExit("Wrong password or damaged file")
    out = src.with_suffix("") if src.suffix == ".enc" else src.with_suffix(".db")
    out.write_bytes(raw)
    print("Written", out, f"({len(raw) // 1024} KB)")
