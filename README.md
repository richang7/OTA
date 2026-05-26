<<<<<<< HEAD
# OTA_test1
=======
# A/B 分区 OTA 升级最小原型项目

本地可运行的 A/B 双槽位 OTA 升级系统原型，使用 Python 3.11+ 实现。

## 项目目录树

```
OTA_test/
├── server/                     # 服务端
│   ├── __init__.py
│   ├── main.py                 # FastAPI 应用入口
│   ├── database.py             # SQLite 数据库
│   ├── models.py               # Pydantic 模型
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── admin.py            # 管理端 API
│   │   └── device.py           # 设备端 API
│   └── static/
│       └── index.html          # Web 管理面板
├── client/                     # 设备端
│   ├── __init__.py
│   ├── __main__.py             # CLI 入口
│   ├── cli.py                  # 设备端 CLI
│   ├── ab_manager.py           # A/B 分区管理器
│   └── device_state/           # 分区状态（运行时生成）
│       ├── boot.json
│       ├── slot_a.img
│       └── slot_b.img
├── tools/                      # 工具脚本
│   ├── gen_keys.py             # 生成 Ed25519 密钥对
│   └── build_artifact.py       # 构建固件工件
├── tests/                      # 自动化测试
│   ├── __init__.py
│   ├── conftest.py             # pytest fixture
│   └── test_ota.py             # 测试用例
├── keys/                       # 密钥文件（运行时生成）
├── firmware_repo/              # 固件仓库（运行时生成）
├── requirements.txt
├── Dockerfile
├── compose.yaml
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 生成密钥对

```bash
python tools/gen_keys.py
```

将在 `keys/` 目录生成 `ed25519_private.pem` 和 `ed25519_public.pem`。

### 3. 创建模拟固件并构建工件

```bash
# 创建 v1.0.0 固件（初始版本）
mkdir -p firmware_repo/raspberrypi/1.0.0
echo "FIRMWARE_V1_INITIAL" > firmware_repo/raspberrypi/1.0.0/rootfs.img

# 创建 v2.0.0 固件（升级版本）
mkdir -p firmware_repo/raspberrypi/2.0.0
echo "FIRMWARE_V2_UPGRADE_DATA_PADDING_1234567890" > firmware_repo/raspberrypi/2.0.0/rootfs.img

# 构建 v2.0.0 工件（计算哈希、生成 manifest、签名）
python tools/build_artifact.py \
    --device-type raspberrypi \
    --version 2.0.0 \
    --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img
```

### 4. 启动 OTA 服务器

```bash
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

或使用 Docker Compose：

```bash
docker compose up --build
```

### 5. 初始化设备

```bash
python -m client.cli init --version 1.0.0
```

### 6. 登记工件 & 创建部署

通过 Web 面板（浏览器打开 http://localhost:8000）或 API：

```bash
# 读取 manifest 获取哈希值
cat firmware_repo/raspberrypi/2.0.0/manifest.json

# 登记工件（替换 SHA256 和 MD5 为实际值）
curl -X POST http://localhost:8000/api/v1/admin/artifacts/register \
  -H "Content-Type: application/json" \
  -d '{
    "device_type": "raspberrypi",
    "version": "2.0.0",
    "filename": "rootfs.img",
    "size": <实际大小>,
    "sha256": "<实际sha256>",
    "md5": "<实际md5>"
  }'

# 创建部署（使用返回的 artifact_id）
curl -X POST http://localhost:8000/api/v1/admin/deployments \
  -H "Content-Type: application/json" \
  -d '{
    "artifact_id": "<artifact_id>",
    "device_type": "raspberrypi"
  }'
```

### 7. 完整升级流程（成功路径）

```bash
# 检查更新
python -m client.cli check --server http://localhost:8000

# 应用更新（需提供 artifact_id 和 installation_id）
python -m client.cli apply \
    --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img \
    --version 2.0.0 \
    --server http://localhost:8000 \
    --artifact-id <artifact_id> \
    --installation-id <installation_id>

# 查看状态
python -m client.cli status

# 模拟重启 —— 启动健康
python -m client.cli reboot --health-ok

# 再次查看状态（确认升级成功）
python -m client.cli status
```

### 8. 升级后回滚流程

```bash
# 重新初始化设备
python -m client.cli init --version 1.0.0

# 应用更新
python -m client.cli apply \
    --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img \
    --version 2.0.0

# 模拟重启 —— 启动失败（连续3次将触发回滚）
python -m client.cli reboot --health-fail
python -m client.cli reboot --health-fail
python -m client.cli reboot --health-fail

# 查看状态（确认已回滚到槽位 A）
python -m client.cli status
```

### 9. 运行测试

```bash
pytest tests/ -v
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/artifacts/register` | 登记固件工件 |
| GET | `/api/v1/admin/artifacts` | 列出所有工件 |
| POST | `/api/v1/admin/deployments` | 创建部署 |
| GET | `/api/v1/admin/deployments` | 列出所有部署 |
| POST | `/api/v1/device/check` | 设备检查更新 |
| GET | `/api/v1/device/artifacts/{id}/manifest` | 获取 manifest（含签名） |
| PUT | `/api/v1/device/installations/{id}/state` | 上报安装状态 |
| GET | `/api/v1/device/installations` | 列出安装记录 |
| GET | `/repo/{device_type}/{version}/{filename}` | 下载固件文件 |

## 设备 CLI 命令

| 命令 | 说明 |
|------|------|
| `init [--version]` | 初始化设备 A/B 槽位 |
| `apply --firmware --version [--server] [--artifact-id] [--installation-id]` | 应用固件更新 |
| `reboot --health-ok` | 启动健康，标记成功 |
| `reboot --health-fail` | 启动失败，触发回滚逻辑 |
| `status` | 显示当前设备状态 |
| `check --server [--device-id] [--device-type]` | 检查服务器更新 |

## 安全机制

- **SHA-256 校验**：设备端下载固件后验证 SHA-256，不匹配则拒绝升级
- **Ed25519 签名**：manifest 使用 Ed25519 签名，设备端验签通过才接受升级
- **MD5 仅展示**：MD5 作为辅助字段，不作为升级判据
- **路径遍历防护**：固件下载接口对路径参数做安全过滤

## A/B 分区回滚机制

1. `apply` 将新固件写入非活动槽位，设置 `pending_slot`
2. `reboot` 时 Bootloader 切换到 `pending_slot`
3. 如果 `--health-ok`，标记成功，清除 pending
4. 如果 `--health-fail`，减少 `boot_attempts_left`
5. 次数耗尽（默认3次），自动回滚到旧槽位

## 真实设备适配说明

代码中标注了以下需要替换的位置：
- `ab_manager.py`：替换为 Bootloader 适配层（U-Boot env / GRUB bootset）
- `cli.py`：替换为嵌入式守护进程（RAUC / hawkBit agent）
- `database.py`：SQLite 替换为云端数据库
- `build_artifact.py`：在 CI/CD 流水线中运行
- `gen_keys.py`：私钥应存入 TPM/SE 安全存储
>>>>>>> 402a1e9 (1)
