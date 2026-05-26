"""管理端 API 路由：工件登记 & 部署创建。"""

import uuid
from typing import List

from fastapi import APIRouter, HTTPException

from server.database import get_connection
from server.models import (
    ArtifactRegisterRequest,
    ArtifactResponse,
    DeploymentCreateRequest,
    DeploymentResponse,
    ErrorResponse,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post(
    "/artifacts/register",
    response_model=ArtifactResponse,
    responses={409: {"model": ErrorResponse}},
)
def register_artifact(req: ArtifactRegisterRequest):
    """登记新固件工件。仅保存元数据，不保存二进制。"""
    artifact_id = f"art-{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        # 检查同 device_type + version 是否已存在
        row = conn.execute(
            "SELECT id FROM artifacts WHERE device_type=? AND version=?",
            (req.device_type, req.version),
        ).fetchone()
        if row:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "ARTIFACT_EXISTS", "message": "该设备类型+版本已存在"},
            )
        conn.execute(
            "INSERT INTO artifacts (id, device_type, version, filename, size, sha256, md5) VALUES (?,?,?,?,?,?,?)",
            (artifact_id, req.device_type, req.version, req.filename, req.size, req.sha256, req.md5),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.get(
    "/artifacts",
    response_model=List[ArtifactResponse],
)
def list_artifacts():
    """列出所有工件。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM artifacts ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post(
    "/deployments",
    response_model=DeploymentResponse,
    responses={404: {"model": ErrorResponse}},
)
def create_deployment(req: DeploymentCreateRequest):
    """创建部署。将工件关联到设备类型，使对应设备可检查到更新。"""
    conn = get_connection()
    try:
        artifact = conn.execute("SELECT * FROM artifacts WHERE id=?", (req.artifact_id,)).fetchone()
        if not artifact:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "ARTIFACT_NOT_FOUND", "message": "工件不存在"},
            )
        deployment_id = f"dep-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO deployments (id, artifact_id, device_type, target_version) VALUES (?,?,?,?)",
            (deployment_id, req.artifact_id, req.device_type, artifact["version"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM deployments WHERE id=?", (deployment_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.get(
    "/deployments",
    response_model=List[DeploymentResponse],
)
def list_deployments():
    """列出所有部署。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM deployments ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
