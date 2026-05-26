#!/usr/bin/env python3
"""构建固件工件：计算哈希、生成 manifest、Ed25519 签名。

用法:
    python tools/build_artifact.py \
        --device-type raspberrypi \
        --version 2.0.0 \
        --firmware ./firmware_repo/raspberrypi/2.0.0/rootfs.img \
        --keys-dir ./keys

在真实设备上，此脚本在 CI/CD 流水线中运行，产出物上传到固件仓库。
"""

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def file_hash(filepath: Path, algo: str = "sha256", chunk_size: int = 8192) -> str:
    """计算文件哈希值。"""
    h = hashlib.new(algo)
    with filepath.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def build_artifact(
    device_type: str,
    version: str,
    firmware_path: Path,
    keys_dir: Path,
    repo_dir: Path,
) -> Path:
    """构建工件目录，返回工件目录路径。"""
    # 读取私钥
    priv_pem = (keys_dir / "ed25519_private.pem").read_bytes()
    private_key = serialization.load_pem_private_key(priv_pem, password=None)

    # 计算哈希
    sha256_val = file_hash(firmware_path, "sha256")
    md5_val = file_hash(firmware_path, "md5")
    file_size = firmware_path.stat().st_size

    # 构建 manifest
    manifest = {
        "device_type": device_type,
        "version": version,
        "filename": firmware_path.name,
        "size": file_size,
        "sha256": sha256_val,
        "md5": md5_val,  # MD5 仅作展示字段，不作为升级判据
    }

    # 规范化 JSON（canonical），用于签名
    # 真实设备上应使用确定性 JSON 序列化（如 RFC 8785）
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    # Ed25519 签名
    signature = private_key.sign(canonical)

    # 输出目录
    out_dir = repo_dir / device_type / version
    out_dir.mkdir(parents=True, exist_ok=True)

    # 复制固件文件
    import shutil
    dst_fw = out_dir / firmware_path.name
    if dst_fw.resolve() != firmware_path.resolve():
        shutil.copy2(firmware_path, dst_fw)

    # 写入 manifest.json
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 写入 manifest.sig（原始二进制签名）
    sig_path = out_dir / "manifest.sig"
    sig_path.write_bytes(signature)

    print(f"工件已生成: {out_dir}")
    print(f"  SHA256: {sha256_val}")
    print(f"  MD5:    {md5_val}")
    print(f"  Size:   {file_size}")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="构建固件工件")
    parser.add_argument("--device-type", required=True, help="设备类型")
    parser.add_argument("--version", required=True, help="固件版本号")
    parser.add_argument(
        "--firmware",
        type=Path,
        required=True,
        help="固件镜像文件路径",
    )
    parser.add_argument(
        "--keys-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "keys",
        help="密钥目录",
    )
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "firmware_repo",
        help="固件仓库根目录",
    )
    args = parser.parse_args()

    if not args.firmware.exists():
        raise FileNotFoundError(f"固件文件不存在: {args.firmware}")

    build_artifact(args.device_type, args.version, args.firmware, args.keys_dir, args.repo_dir)


if __name__ == "__main__":
    main()
