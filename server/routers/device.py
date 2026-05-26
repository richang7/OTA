"""设备端 API 路由：检查更新、获取 manifest、上报安装状态。"""

import json
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from server.database import get_connection
from server.models import (
    DeviceCheckRequest,
    DeviceCheckResponse,
    ErrorResponse,
    InstallationResponse,
    InstallationStateUpdate,
)

router = APIRouter(prefix="/api/v1/device", tags=["device"])

# 固件仓库根目录（可通过 monkeypatch 替换）
REPO_DIR = Path(__file__).resolve().parent.parent.parent / "firmware_repo"


def get_repo_dir() -> Path:
    """获取固件仓库目录，支持运行时替换。"""
    return REPO_DIR

# 允许的安装状态迁移
VALID_STATES = {"downloading", "downloaded", "applying", "applied", "success", "failed"}


@router.post(
    "/check",
    response_model=DeviceCheckResponse,
)
def device_check(req: DeviceCheckRequest):
    """设备检查是否有可用更新。"""
    conn = get_connection()
    try:
        # 查找该设备类型且版本号不同于当前的部署
        deployment = conn.execute(
            """
            SELECT d.*, a.filename, a.sha256, a.md5, a.size, a.version AS artifact_version
            FROM deployments d
            JOIN artifacts a ON d.artifact_id = a.id
            WHERE d.device_type = ?
            ORDER BY d.created_at DESC
            LIMIT 1
            """,
            (req.device_type,),
        ).fetchone()

        if not deployment or deployment["target_version"] == req.current_version:
            return DeviceCheckResponse(has_update=False)

        # 检查是否已有安装记录
        installation = conn.execute(
            "SELECT * FROM installations WHERE device_id=? AND deployment_id=?",
            (req.device_id, deployment["id"]),
        ).fetchone()

        if not installation:
            # 创建安装记录
            inst_id = f"inst-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO installations (id, device_id, deployment_id, artifact_id, state) VALUES (?,?,?,?,?)",
                (inst_id, req.device_id, deployment["id"], deployment["artifact_id"], "pending"),
            )
            conn.commit()
            installation = conn.execute(
                "SELECT * FROM installations WHERE id=?", (inst_id,)
            ).fetchone()

        return DeviceCheckResponse(
            has_update=True,
            installation=dict(installation),
            artifact_id=deployment["artifact_id"],
        )
    finally:
        conn.close()


@router.get(
    "/artifacts/{artifact_id}/manifest",
    responses={404: {"model": ErrorResponse}},
)
def get_manifest(artifact_id: str):
    """获取工件 manifest（含签名）。"""
    conn = get_connection()
    try:
        artifact = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if not artifact:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "ARTIFACT_NOT_FOUND", "message": "工件不存在"},
            )

        device_type = artifact["device_type"]
        version = artifact["version"]
        repo_dir = get_repo_dir()
        manifest_path = repo_dir / device_type / version / "manifest.json"
        sig_path = repo_dir / device_type / version / "manifest.sig"

        if not manifest_path.exists():
            raise HTTPException(
                status_code=404,
                detail={"error_code": "MANIFEST_NOT_FOUND", "message": "manifest 文件不存在"},
            )

        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        # 附加签名（base64 编码方便 JSON 传输）
        sig_bytes = sig_path.read_bytes() if sig_path.exists() else b""
        import base64
        manifest_data["signature_b64"] = base64.b64encode(sig_bytes).decode("ascii")

        return manifest_data
    finally:
        conn.close()


@router.put(
    "/installations/{installation_id}/state",
    response_model=InstallationResponse,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
def update_installation_state(installation_id: str, req: InstallationStateUpdate):
    """设备上报安装状态。支持幂等 PUT。"""
    if req.state not in VALID_STATES:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_STATE", "message": f"无效状态，允许值: {VALID_STATES}"},
        )

    conn = get_connection()
    try:
        installation = conn.execute(
            "SELECT * FROM installations WHERE id=?", (installation_id,)
        ).fetchone()
        if not installation:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "INSTALLATION_NOT_FOUND", "message": "安装记录不存在"},
            )

        # 幂等：如果状态相同，直接返回
        if installation["state"] == req.state:
            return dict(installation)

        conn.execute(
            "UPDATE installations SET state=?, updated_at=datetime('now') WHERE id=?",
            (req.state, installation_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM installations WHERE id=?", (installation_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.get(
    "/installations",
    response_model=List[InstallationResponse],
)
def list_installations():
    """列出所有安装记录。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM installations ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── 固件文件下载 ───
# 此路由挂载在 /repo/ 下，供设备下载固件二进制
repo_router = APIRouter(prefix="/repo", tags=["repo"])


@repo_router.get(
    "/{device_type}/{version}/{filename}",
    responses={404: {"model": ErrorResponse}},
)
def download_firmware(device_type: str, version: str, filename: str):
    """下载固件文件。"""
    # 安全校验：防止路径遍历
    safe_name = Path(filename).name
    safe_type = Path(device_type).name
    safe_version = Path(version).name

    file_path = get_repo_dir() / safe_type / safe_version / safe_name
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "FILE_NOT_FOUND", "message": "固件文件不存在"},
        )
    return FileResponse(str(file_path), filename=safe_name)
