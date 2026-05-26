"""FastAPI 应用入口。

启动方式:
    uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.database import init_db
from server.routers import admin, device

app = FastAPI(title="OTA Upgrade Server", version="0.1.0")

# CORS —— 本地开发允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化数据库
init_db()

# 注册路由
app.include_router(admin.router)
app.include_router(device.router)
app.include_router(device.repo_router)

# 静态前端
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
