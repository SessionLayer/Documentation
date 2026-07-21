#!/usr/bin/env python3
"""Decrypt a SessionLayer recording object (SLREC1) with the customer private key.

Mirrors the platform's seal format (Gateway `ssh/recorder/seal.rs`; the Dashboard
player's `src/crypto/slrec.ts` is the same mirror in the browser):

    header = "SLREC1" | alg(1) | reserved(1) | ephLen(u16 BE) | ephPub(SEC1) |
             wrapNonce(12) | wrapLen(u16 BE) | wrappedKey
    frame  = ctLen(u32 BE) | AES-256-GCM ciphertext (nonce = frame counter,
             AAD = frame index — so a removed/reordered frame fails to decrypt)

The data key is unwrapped via ECIES: ECDH(customer private, ephemeral public)
-> HKDF-SHA256 -> AES-256-GCM key unwrap. Only the holder of the customer
PRIVATE key can do this — the platform stores the public half only and cannot
decrypt its own recordings.

Output: the original asciicast v2 bytes on stdout, or with --text just the
terminal output stream, rendered readable.
"""

import argparse
import json
import struct
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import load_pem_private_key

MAGIC = b"SLREC1"
ALG_ECIES_P256 = 1
KEK_INFO = b"SessionLayer/recording/ECIES-P256-HKDF-SHA256/kek/v1"
WRAP_AAD = b"SessionLayer/recording/data-key-wrap/v1"


def fail(msg: str) -> None:
    print(f"decrypt_slrec: {msg}", file=sys.stderr)
    sys.exit(1)


def unseal(obj: bytes, key_pem: bytes) -> bytes:
    if obj[:6] != MAGIC:
        fail("not a SLREC1 recording object (bad magic)")
    alg = obj[6]
    if alg != ALG_ECIES_P256:
        fail(f"unsupported seal algorithm {alg}")
    off = 8
    (eph_len,) = struct.unpack_from(">H", obj, off)
    off += 2
    eph_pub = obj[off : off + eph_len]
    off += eph_len
    wrap_nonce = obj[off : off + 12]
    off += 12
    (wrap_len,) = struct.unpack_from(">H", obj, off)
    off += 2
    wrapped_key = obj[off : off + wrap_len]
    off += wrap_len

    private_key = load_pem_private_key(key_pem, password=None)
    ephemeral = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes(eph_pub))
    shared = private_key.exchange(ec.ECDH(), ephemeral)
    kek = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=KEK_INFO + bytes(eph_pub)
    ).derive(shared)
    try:
        data_key = AESGCM(kek).decrypt(bytes(wrap_nonce), bytes(wrapped_key), WRAP_AAD)
    except Exception:
        fail("wrong customer key for this recording (key unwrap failed)")

    out = bytearray()
    index = 0
    while off < len(obj):
        (ct_len,) = struct.unpack_from(">I", obj, off)
        off += 4
        ct = obj[off : off + ct_len]
        off += ct_len
        nonce = struct.pack(">4xQ", index)
        try:
            out += AESGCM(data_key).decrypt(nonce, bytes(ct), struct.pack(">Q", index))
        except Exception:
            fail(f"frame {index} failed to decrypt (tampered or truncated object)")
        index += 1
    return bytes(out)


def render_text(cast: bytes) -> str:
    # asciicast v2: a JSON header line, then [time, kind, data] events; "o" is
    # terminal output ("i" is captured keystrokes — deliberately not echoed here).
    out = []
    for line in cast.decode("utf-8", errors="replace").splitlines()[1:]:
        if not line:
            continue
        event = json.loads(line)
        if event[1] == "o":
            out.append(event[2])
    return "".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("object", help="the sealed recording object (SLREC1)")
    parser.add_argument(
        "--key",
        default="/keys/customer_key.pem",
        help="customer PRIVATE key, PEM (default: the quickstart demo key)",
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="print the recorded terminal output instead of the raw asciicast",
    )
    args = parser.parse_args()

    with open(args.object, "rb") as f:
        obj = f.read()
    with open(args.key, "rb") as f:
        key_pem = f.read()

    cast = unseal(obj, key_pem)
    if args.text:
        sys.stdout.write(render_text(cast))
    else:
        sys.stdout.buffer.write(cast)


if __name__ == "__main__":
    main()
