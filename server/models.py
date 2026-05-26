"""Pydantic 数据模型 —— 请求/响应结构体。"""

from typing import Optional

from pydantic import BaseModel, Field


# ─── 通用错误响应 ───
class ErrorResponse(BaseModel):
    error_code: str
    message: str


# ─── 工件（Artifact） ───
class ArtifactRegisterRequest(BaseModel):
    device_type: str = Field(..., description="设备类型，如 raspberrypi")
    version: str = Field(..., description="固件版本号，如 2.0.0")
    filename: str = Field(..., description="固件文件名，如 rootfs.img")
    size: int = Field(..., gt=0, description="文件大小（字节）")
    sha256: str = Field(..., min_length=64, max_length=64, description="SHA-256 哈希")
    md5: str = Field(..., min_length=32, max_length=32, description="MD5 哈希（仅展示）")


class ArtifactResponse(BaseModel):
    id: str
    device_type: str
    version: str
    filename: str
    size: int
    sha256: str
    md5: str
    created_at: str


# ─── 部署（Deployment） ───
class DeploymentCreateRequest(BaseModel):
    artifact_id: str = Field(..., description="工件 ID")
    device_type: str = Field(..., description="目标设备类型")


class DeploymentResponse(BaseModel):
    id: str
    artifact_id: str
    device_type: str
    target_version: str
    created_at: str


# ─── 设备检查 ───
class DeviceCheckRequest(BaseModel):
    device_id: str = Field(..., description="设备唯一标识")
    device_type: str = Field(..., description="设备类型")
    current_version: str = Field(..., description="当前固件版本")


class DeviceCheckResponse(BaseModel):
    has_update: bool
    installation: Optional[dict] = None
    artifact_id: Optional[str] = None


# ─── 安装状态 ───
class InstallationStateUpdate(BaseModel):
    state: str = Field(..., description="新状态: downloading|downloaded|applying|applied|success|failed")


class InstallationResponse(BaseModel):
    id: str
    device_id: str
    deployment_id: str
    artifact_id: str
    state: str
    created_at: str
    updated_at: str
