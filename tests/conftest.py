"""pytest 测试配置 —— 共享 fixture。"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import DB_PATH, get_connection, init_db
from server.main import app
from client.ab_manager import ABManager


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    """每个测试使用独立的临时数据库。"""
    db_file = tmp_path / "test_ota.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file)
    init_db(db_file)
    yield
    # 清理


@pytest.fixture
def client():
    """FastAPI 测试客户端。"""
    return TestClient(app)


@pytest.fixture
def ab_manager(tmp_path):
    """独立的 A/B 管理器（使用临时目录）。"""
    state_dir = tmp_path / "device_state"
    mgr = ABManager(state_dir)
    mgr.init_slots("1.0.0")
    return mgr


@pytest.fixture
def keys_dir(tmp_path):
    """生成临时 Ed25519 密钥对。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    kdir = tmp_path / "keys"
    kdir.mkdir()

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    (kdir / "ed25519_private.pem").write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    (kdir / "ed25519_public.pem").write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return kdir


@pytest.fixture
def firmware_file(tmp_path):
    """创建临时固件文件。"""
    fw = tmp_path / "firmware_repo" / "raspberrypi" / "2.0.0"
    fw.mkdir(parents=True)
    img = fw / "rootfs.img"
    img.write_bytes(b"FIRMWARE_V2_TEST_DATA_" * 100)
    return img


@pytest.fixture
def built_artifact(firmware_file, keys_dir, tmp_path):
    """构建完整工件（含 manifest 和签名）。"""
    from tools.build_artifact import build_artifact

    repo_dir = tmp_path / "firmware_repo"
    out_dir = build_artifact(
        device_type="raspberrypi",
        version="2.0.0",
        firmware_path=firmware_file,
        keys_dir=keys_dir,
        repo_dir=repo_dir,
    )
    return out_dir
