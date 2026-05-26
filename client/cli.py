#!/usr/bin/env python3
"""设备端 OTA CLI —— 支持 init / apply / reboot / status 命令。

用法:
    python -m client.cli init [--version 1.0.0]
    python -m client.cli apply --firmware <path> --version <ver> [--server http://localhost:8000]
    python -m client.cli reboot --health-ok
    python -m client.cli reboot --health-fail
    python -m client.cli status

在真实设备上，此 CLI 替换为嵌入式应用层守护进程（如 RAUC/hawkBit agent）。
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import urllib.request
import urllib.error

from client.ab_manager import ABManager, DEFAULT_STATE_DIR

# 公钥路径（验签用）
DEFAULT_KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"


def _http_request(url: str, data: dict = None, method: str = "GET") -> dict:
    """简易 HTTP 请求封装。"""
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error_code": "HTTP_ERROR", "message": f"HTTP {e.code}: {body}"}


def _verify_signature(manifest: dict, signature_b64: str, public_key_path: Path) -> bool:
    """验证 Ed25519 签名。

    设备端接受升级的判据：SHA-256 + Ed25519 签名通过。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    import base64

    if not public_key_path.exists():
        print(f"[ERROR] 公钥文件不存在: {public_key_path}")
        return False

    pub_pem = public_key_path.read_bytes()
    public_key = serialization.load_pem_public_key(pub_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        print("[ERROR] 公钥类型不是 Ed25519")
        return False

    # 重建 canonical manifest（与 build_artifact.py 一致）
    # 移除签名字段后排序序列化
    manifest_copy = {k: v for k, v in manifest.items() if k != "signature_b64"}
    canonical = json.dumps(manifest_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    signature = base64.b64decode(signature_b64)
    try:
        public_key.verify(signature, canonical)
        return True
    except Exception as e:
        print(f"[ERROR] 签名验证失败: {e}")
        return False


def _verify_sha256(filepath: Path, expected_sha256: str) -> bool:
    """验证文件 SHA-256。"""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected_sha256:
        print(f"[ERROR] SHA-256 不匹配: 期望 {expected_sha256}, 实际 {actual}")
        return False
    return True


# ─── 子命令 ───


def cmd_init(args: argparse.Namespace) -> None:
    """初始化设备 A/B 槽位。"""
    mgr = ABManager()
    mgr.init_slots(initial_version=args.version)
    print(f"设备初始化完成, 当前槽位 A, 版本 {args.version}")


def cmd_apply(args: argparse.Namespace) -> None:
    """应用固件更新到非活动槽位。"""
    firmware_path = Path(args.firmware).resolve()
    if not firmware_path.exists():
        print(f"[ERROR] 固件文件不存在: {firmware_path}")
        sys.exit(1)

    mgr = ABManager()

    # 从服务器获取 manifest 并验证
    if args.artifact_id and args.server:
        print(f"从服务器获取 manifest (artifact_id={args.artifact_id})...")
        manifest_url = f"{args.server}/api/v1/device/artifacts/{args.artifact_id}/manifest"
        manifest = _http_request(manifest_url)

        if "error_code" in manifest:
            print(f"[ERROR] 获取 manifest 失败: {manifest.get('message')}")
            sys.exit(1)

        # 验证签名
        sig_b64 = manifest.get("signature_b64", "")
        pub_key_path = DEFAULT_KEYS_DIR / "ed25519_public.pem"
        if not _verify_signature(manifest, sig_b64, pub_key_path):
            print("[ERROR] 签名验证失败，拒绝升级！")
            sys.exit(1)
        print("[OK] Ed25519 签名验证通过")

        # 验证 SHA-256
        if not _verify_sha256(firmware_path, manifest["sha256"]):
            print("[ERROR] SHA-256 校验失败，拒绝升级！")
            sys.exit(1)
        print("[OK] SHA-256 校验通过")

    # 写入非活动槽位
    target_slot = mgr.apply_update(firmware_path, args.version)
    print(f"[OK] 固件已写入槽位 {target_slot.upper()}, 版本 {args.version}")
    print(f"[OK] 重启后将切换到槽位 {target_slot.upper()}")

    # 上报状态
    if args.installation_id and args.server:
        state_url = f"{args.server}/api/v1/device/installations/{args.installation_id}/state"
        _http_request(state_url, {"state": "applied"}, method="PUT")
        print("[OK] 已上报 applied 状态")


def cmd_reboot(args: argparse.Namespace) -> None:
    """模拟重启 —— 切换到 pending 槽位，然后根据健康状态处理。"""
    mgr = ABManager()
    cfg = mgr.read_boot_config()

    # 如果有 pending_slot 且与当前不同，先切换
    if cfg.pending_slot and cfg.pending_slot != cfg.current_slot:
        print(f"重启: 从槽位 {cfg.current_slot.upper()} 切换到 {cfg.pending_slot.upper()}")
        mgr.switch_to_pending()
    else:
        print(f"重启: 继续使用槽位 {cfg.current_slot.upper()}")

    if args.health_ok:
        cfg = mgr.reboot_health_ok()
        print(f"[OK] 启动健康，槽位 {cfg.current_slot.upper()} 标记为成功")
    elif args.health_fail:
        cfg = mgr.reboot_health_fail()
        if cfg.successful and not cfg.pending_slot:
            print(f"[ROLLBACK] 启动失败次数耗尽，已回滚到槽位 {cfg.current_slot.upper()}")
        else:
            print(f"[WARN] 启动失败，剩余尝试次数: {cfg.boot_attempts_left}")


def cmd_status(args: argparse.Namespace) -> None:
    """显示当前设备状态。"""
    mgr = ABManager()
    cfg = mgr.read_boot_config()

    print("=== 设备 A/B 状态 ===")
    print(f"  当前槽位:   {cfg.current_slot.upper()}")
    print(f"  待切换槽位: {cfg.pending_slot.upper() if cfg.pending_slot else '无'}")
    print(f"  启动成功:   {'是' if cfg.successful else '否'}")
    print(f"  剩余尝试:   {cfg.boot_attempts_left}")
    print(f"  槽位 A 版本: {mgr.get_slot_version('a')}")
    print(f"  槽位 B 版本: {mgr.get_slot_version('b')}")


def cmd_check(args: argparse.Namespace) -> None:
    """向服务器检查是否有可用更新。"""
    if not args.server:
        print("[ERROR] 需要指定 --server")
        sys.exit(1)

    mgr = ABManager()
    current_version = mgr.get_slot_version(mgr.get_active_slot())

    payload = {
        "device_id": args.device_id,
        "device_type": args.device_type,
        "current_version": current_version,
    }
    result = _http_request(f"{args.server}/api/v1/device/check", payload, method="POST")

    if result.get("has_update"):
        print(f"[UPDATE] 发现新版本！")
        inst = result.get("installation", {})
        print(f"  安装 ID:   {inst.get('id', 'N/A')}")
        print(f"  工件 ID:   {result.get('artifact_id', 'N/A')}")
        print(f"  当前状态:  {inst.get('state', 'N/A')}")
    else:
        print("[OK] 已是最新版本")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ota-client",
        description="OTA 设备端 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # init
    p_init = subparsers.add_parser("init", help="初始化设备")
    p_init.add_argument("--version", default="1.0.0", help="初始版本号")

    # apply
    p_apply = subparsers.add_parser("apply", help="应用固件更新")
    p_apply.add_argument("--firmware", required=True, help="固件文件路径")
    p_apply.add_argument("--version", required=True, help="目标版本号")
    p_apply.add_argument("--server", default=None, help="OTA 服务器地址")
    p_apply.add_argument("--artifact-id", default=None, help="工件 ID（用于获取 manifest）")
    p_apply.add_argument("--installation-id", default=None, help="安装记录 ID")

    # reboot
    p_reboot = subparsers.add_parser("reboot", help="模拟重启")
    p_reboot.add_argument("--health-ok", action="store_true", help="启动健康")
    p_reboot.add_argument("--health-fail", action="store_true", help="启动失败")

    # status
    subparsers.add_parser("status", help="显示设备状态")

    # check
    p_check = subparsers.add_parser("check", help="检查服务器更新")
    p_check.add_argument("--server", default="http://localhost:8000", help="OTA 服务器地址")
    p_check.add_argument("--device-id", default="device-001", help="设备 ID")
    p_check.add_argument("--device-type", default="raspberrypi", help="设备类型")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "apply":
        cmd_apply(args)
    elif args.command == "reboot":
        cmd_reboot(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "check":
        cmd_check(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
