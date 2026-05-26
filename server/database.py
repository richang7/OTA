"""SQLite 数据库初始化与连接管理。

所有元数据与状态保存在 SQLite，固件二进制不存数据库。
在真实设备上，此层替换为云端数据库（如 PostgreSQL）。
"""

import sqlite3
from pathlib import Path
from typing import Optional

# 数据库文件路径
DB_PATH: Path = Path(__file__).resolve().parent.parent / "ota.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """获取 SQLite 连接，启用 WAL 模式和外键约束。"""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """初始化数据库表结构。"""
    conn = get_connection(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                device_type TEXT NOT NULL,
                version TEXT NOT NULL,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                md5 TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS deployments (
                id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL REFERENCES artifacts(id),
                device_type TEXT NOT NULL,
                target_version TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS installations (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                deployment_id TEXT NOT NULL REFERENCES deployments(id),
                artifact_id TEXT NOT NULL REFERENCES artifacts(id),
                state TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(device_id, deployment_id)
            );
        """)
        conn.commit()
    finally:
        conn.close()
