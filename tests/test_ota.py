"""OTA 自动化测试。

覆盖场景:
1. 成功升级流程
2. 签名验证失败
3. SHA-256 不匹配
4. 重复 PUT state 幂等
5. 启动失败后回滚
"""

import base64
import hashlib
import json
from pathlib import Path

from client.ab_manager import ABManager
from tools.build_artifact import build_artifact


# ─── 1. 成功升级流程 ───


def test_successful_upgrade(client, ab_manager, keys_dir, firmware_file, tmp_path, monkeypatch):
    """测试完整的成功升级流程：登记 -> 部署 -> 检查 -> 下载 -> 验签 -> 应用 -> 重启健康。"""
    repo_dir = tmp_path / "firmware_repo"

    # 构建工件
    out_dir = build_artifact("raspberrypi", "2.0.0", firmware_file, keys_dir, repo_dir)

    # 让服务端从临时仓库读取 manifest
    monkeypatch.setattr("server.routers.device.REPO_DIR", repo_dir)

    # 读取 manifest 获取哈希
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    # 登记工件
    res = client.post("/api/v1/admin/artifacts/register", json={
        "device_type": "raspberrypi",
        "version": "2.0.0",
        "filename": "rootfs.img",
        "size": manifest["size"],
        "sha256": manifest["sha256"],
        "md5": manifest["md5"],
    })
    assert res.status_code == 200
    artifact_id = res.json()["id"]

    # 创建部署
    res = client.post("/api/v1/admin/deployments", json={
        "artifact_id": artifact_id,
        "device_type": "raspberrypi",
    })
    assert res.status_code == 200
    deployment_id = res.json()["id"]

    # 设备检查更新
    res = client.post("/api/v1/device/check", json={
        "device_id": "device-001",
        "device_type": "raspberrypi",
        "current_version": "1.0.0",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["has_update"] is True
    installation_id = data["installation"]["id"]

    # 获取 manifest（含签名）
    res = client.get(f"/api/v1/device/artifacts/{artifact_id}/manifest")
    assert res.status_code == 200
    manifest_data = res.json()
    assert "signature_b64" in manifest_data

    # 验证签名
    from client.cli import _verify_signature
    monkeypatch.setattr("client.cli.DEFAULT_KEYS_DIR", keys_dir)
    assert _verify_signature(manifest_data, manifest_data["signature_b64"], keys_dir / "ed25519_public.pem")

    # 验证 SHA-256
    from client.cli import _verify_sha256
    assert _verify_sha256(firmware_file, manifest_data["sha256"])

    # 应用更新到非活动槽位
    target_slot = ab_manager.apply_update(firmware_file, "2.0.0")
    assert target_slot == "b"

    # 上报 applied 状态
    res = client.put(f"/api/v1/device/installations/{installation_id}/state", json={"state": "applied"})
    assert res.status_code == 200

    # 模拟重启 —— 切换到新槽位
    ab_manager.switch_to_pending()
    cfg = ab_manager.read_boot_config()
    assert cfg.current_slot == "b"

    # 启动健康
    cfg = ab_manager.reboot_health_ok()
    assert cfg.successful is True
    assert cfg.pending_slot is None


# ─── 2. 签名验证失败 ───


def test_signature_verification_fails(keys_dir, firmware_file, tmp_path, monkeypatch):
    """使用错误密钥签名，设备端应验签失败。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    # 用另一对密钥签名
    wrong_key = Ed25519PrivateKey.generate()
    repo_dir = tmp_path / "firmware_repo"
    out_dir = build_artifact("raspberrypi", "2.0.0", firmware_file, keys_dir, repo_dir)

    # 读取 manifest 并用错误密钥重新签名
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    wrong_sig = wrong_key.sign(canonical)

    manifest_data = manifest.copy()
    manifest_data["signature_b64"] = base64.b64encode(wrong_sig).decode("ascii")

    # 验签应失败
    from client.cli import _verify_signature
    result = _verify_signature(manifest_data, manifest_data["signature_b64"], keys_dir / "ed25519_public.pem")
    assert result is False


# ─── 3. SHA-256 不匹配 ───


def test_sha256_mismatch(firmware_file, tmp_path):
    """文件被篡改后 SHA-256 校验应失败。"""
    from client.cli import _verify_sha256

    # 计算正确哈希
    correct_hash = hashlib.sha256(firmware_file.read_bytes()).hexdigest()

    # 创建被篡改的文件
    tampered = tmp_path / "tampered.img"
    tampered.write_bytes(b"TAMPERED_DATA")

    # 用正确的哈希校验篡改文件，应失败
    assert _verify_sha256(tampered, correct_hash) is False


# ─── 4. 重复 PUT state 幂等 ───


def test_idempotent_state_update(client, keys_dir, firmware_file, tmp_path):
    """重复 PUT 相同状态应幂等返回。"""
    repo_dir = tmp_path / "firmware_repo"
    out_dir = build_artifact("raspberrypi", "2.0.0", firmware_file, keys_dir, repo_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    # 登记工件
    res = client.post("/api/v1/admin/artifacts/register", json={
        "device_type": "raspberrypi",
        "version": "2.0.0",
        "filename": "rootfs.img",
        "size": manifest["size"],
        "sha256": manifest["sha256"],
        "md5": manifest["md5"],
    })
    artifact_id = res.json()["id"]

    # 创建部署
    res = client.post("/api/v1/admin/deployments", json={
        "artifact_id": artifact_id,
        "device_type": "raspberrypi",
    })

    # 检查更新（创建安装记录）
    res = client.post("/api/v1/device/check", json={
        "device_id": "device-001",
        "device_type": "raspberrypi",
        "current_version": "1.0.0",
    })
    installation_id = res.json()["installation"]["id"]

    # 第一次 PUT
    res1 = client.put(f"/api/v1/device/installations/{installation_id}/state", json={"state": "downloading"})
    assert res1.status_code == 200

    # 第二次 PUT 相同状态（幂等）
    res2 = client.put(f"/api/v1/device/installations/{installation_id}/state", json={"state": "downloading"})
    assert res2.status_code == 200
    assert res1.json()["state"] == res2.json()["state"]


# ─── 5. 启动失败后回滚 ───


def test_rollback_on_boot_failure(ab_manager, firmware_file):
    """升级后启动失败，次数耗尽后自动回滚到旧槽位。"""
    # 初始状态：槽位 A，版本 1.0.0
    assert ab_manager.get_active_slot() == "a"

    # 应用更新到槽位 B
    ab_manager.apply_update(firmware_file, "2.0.0")

    # 切换到新槽位
    ab_manager.switch_to_pending()
    assert ab_manager.get_active_slot() == "b"

    # 第一次启动失败
    cfg = ab_manager.reboot_health_fail()
    assert cfg.boot_attempts_left == 2
    assert cfg.current_slot == "b"  # 还没回滚

    # 第二次启动失败
    cfg = ab_manager.reboot_health_fail()
    assert cfg.boot_attempts_left == 1
    assert cfg.current_slot == "b"

    # 第三次启动失败 —— 次数耗尽，回滚
    cfg = ab_manager.reboot_health_fail()
    assert cfg.boot_attempts_left == 0
    assert cfg.current_slot == "a"  # 回滚到旧槽位
    assert cfg.successful is True
    assert cfg.pending_slot is None


# ─── 额外：设备初始化 ───


def test_device_init(ab_manager):
    """测试设备初始化。"""
    cfg = ab_manager.read_boot_config()
    assert cfg.current_slot == "a"
    assert cfg.successful is True
    assert cfg.pending_slot is None
    assert ab_manager.get_slot_version("a") == "1.0.0"


# ─── 额外：工件重复登记 ───


def test_duplicate_artifact_registration(client, keys_dir, firmware_file, tmp_path):
    """同 device_type + version 重复登记应返回 409。"""
    repo_dir = tmp_path / "firmware_repo"
    out_dir = build_artifact("raspberrypi", "2.0.0", firmware_file, keys_dir, repo_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    payload = {
        "device_type": "raspberrypi",
        "version": "2.0.0",
        "filename": "rootfs.img",
        "size": manifest["size"],
        "sha256": manifest["sha256"],
        "md5": manifest["md5"],
    }

    # 第一次成功
    res1 = client.post("/api/v1/admin/artifacts/register", json=payload)
    assert res1.status_code == 200

    # 第二次冲突
    res2 = client.post("/api/v1/admin/artifacts/register", json=payload)
    assert res2.status_code == 409
