#!/usr/bin/env python3
"""生成 Ed25519 公私钥 PEM 文件。

用法:
    python tools/gen_keys.py [--keys-dir ./keys]

在真实设备上，私钥应保存在安全存储区（如 TPM/SE），公钥嵌入固件用于验签。
"""

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keys(keys_dir: Path) -> None:
    keys_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # 保存私钥（PKCS8 PEM）
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    priv_path = keys_dir / "ed25519_private.pem"
    priv_path.write_bytes(priv_pem)
    print(f"私钥已写入: {priv_path}")

    # 保存公钥（PKCS8 PEM）
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path = keys_dir / "ed25519_public.pem"
    pub_path.write_bytes(pub_pem)
    print(f"公钥已写入: {pub_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Ed25519 密钥对")
    parser.add_argument(
        "--keys-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "keys",
        help="密钥输出目录",
    )
    args = parser.parse_args()
    generate_keys(args.keys_dir)


if __name__ == "__main__":
    main()
