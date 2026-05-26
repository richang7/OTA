# A/B 分区 OTA 升级 —— 完整操作指南

## 环境准备

> 以下命令在 PowerShell 中执行，Windows/macOS/Linux 均可运行。

### 1. 创建并激活 Conda 环境

```powershell
conda create -n OTA_test python=3.11 -y
conda activate OTA_test
cd D:\Codes\OTA_test
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. 生成 Ed25519 密钥对

```powershell
python tools/gen_keys.py
```

输出：
```
私钥已写入: D:\Codes\OTA_test\keys\ed25519_private.pem
公钥已写入: D:\Codes\OTA_test\keys\ed25519_public.pem
```

### 4. 创建模拟固件文件

```powershell
New-Item -ItemType Directory -Force -Path "firmware_repo\raspberrypi\2.0.0"
Set-Content -Path "firmware_repo\raspberrypi\2.0.0\rootfs.img" -Value "FIRMWARE_V2_UPGRADE_DATA_PADDING_1234567890" -NoNewline
```

### 5. 构建工件（计算哈希、生成 manifest、Ed25519 签名）

```powershell
python tools/build_artifact.py --device-type raspberrypi --version 2.0.0 --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img
```

输出：
```
工件已生成: D:\Codes\OTA_test\firmware_repo\raspberrypi\2.0.0
  SHA256: 145a7ef470cf433869d42f618ee7539754c840b03fe4fbbe13bce5f733ec9320
  MD5:    ec76d50e57221685fbea1a77970cb41f
  Size:   43
```

**记下 SHA-256 和 MD5 值，下一步要用。**

---

## 启动服务器

在 **终端 1** 中执行（保持运行，不要关闭）：

```powershell
conda activate OTA_test
cd D:\Codes\OTA_test
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

看到以下输出说明启动成功：
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

> 如果端口被占用，先杀掉占用进程：
> ```powershell
> Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force
> ```

---

## 登记工件 & 创建部署

打开浏览器访问 http://localhost:8000

### 方式 A：网页操作（推荐）

1. 在 **"登记工件"** 卡片中填入：
   - 设备类型：`raspberrypi`
   - 版本号：`2.0.0`
   - 文件名：`rootfs.img`
   - 文件大小：`43`
   - SHA-256：粘贴第5步输出的值
   - MD5：粘贴第5步输出的值
   - 点击 **"登记"**

2. 登记成功后，工件 ID 会自动填入 **"创建部署"** 卡片：
   - 设备类型填 `raspberrypi`
   - 点击 **"创建"**

3. 下方列表会显示已登记的工件和部署记录

### 方式 B：终端操作

```powershell
# 登记工件（替换 <sha256> 和 <md5> 为实际值）
$body = '{"device_type":"raspberrypi","version":"2.0.0","filename":"rootfs.img","size":43,"sha256":"<sha256>","md5":"<md5>"}'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/admin/artifacts/register' -Method POST -ContentType 'application/json' -Body $body

# 记下返回的 id（如 art-xxxxxxxxxxxx），创建部署
$body = '{"artifact_id":"art-xxxxxxxxxxxx","device_type":"raspberrypi"}'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/admin/deployments' -Method POST -ContentType 'application/json' -Body $body
```

---

## 设备端操作

**另开一个终端（终端 2）**，服务器保持运行：

```powershell
conda activate OTA_test
cd D:\Codes\OTA_test
```

---

### 场景一：成功升级（A → B）

#### 步骤 1：检查当前版本号

```powershell
python -m client.cli init --version 1.0.0
python -m client.cli check --server http://127.0.0.1:8000
```

输出：
```
[UPDATE] 发现新版本！
  安装 ID:   inst-54168cf8a254
  工件 ID:   art-2c99b7a6df2d
  当前状态:  pending
```

**记下安装 ID 和工件 ID。**

#### 步骤 2：下载新固件 + 校验 SHA256/签名 + 写入非活动分区

```powershell
python -m client.cli apply --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img --version 2.0.0 --server http://127.0.0.1:8000 --artifact-id <工件ID> --installation-id <安装ID>

python -m client.cli apply --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img --version 2.0.0 --server http://127.0.0.1:8000 --artifact-id art-2c99b7a6df2d --installation-id inst-54168cf8a254
```

输出：
```
从服务器获取 manifest (artifact_id=art-xxxxxxxxxxxx)...
[OK] Ed25519 签名验证通过
[OK] SHA-256 校验通过
[OK] 固件已写入槽位 B, 版本 2.0.0
[OK] 重启后将切换到槽位 B
[OK] 已上报 applied 状态
```

#### 步骤 3：查看当前状态

```powershell
python -m client.cli status
```

输出：
```
=== 设备 A/B 状态 ===
  当前槽位:   A
  待切换槽位: B
  启动成功:   否
  剩余尝试:   3
  槽位 A 版本: 1.0.0
  槽位 B 版本: 2.0.0
```

#### 步骤 4：模拟重启 —— 启动健康，切换到新分区

```powershell
python -m client.cli reboot --health-ok
```

输出：
```
重启: 从槽位 A 切换到 B
[OK] 启动健康，槽位 B 标记为成功
```

#### 步骤 5：确认升级成功

```powershell
python -m client.cli status
```

输出：
```
=== 设备 A/B 状态 ===
  当前槽位:   B
  待切换槽位: 无
  启动成功:   是
  剩余尝试:   0
  槽位 A 版本: 1.0.0
  槽位 B 版本: 2.0.0
```

**升级成功！当前运行在槽位 B，版本 2.0.0。**

---

### 场景二：升级失败自动回滚

#### 步骤 1：重新初始化设备

```powershell
python -m client.cli init --version 1.0.0
```

#### 步骤 2：应用更新

```powershell
python -m client.cli apply --firmware firmware_repo/raspberrypi/2.0.0/rootfs.img --version 2.0.0
```

#### 步骤 3：连续 3 次启动失败，触发自动回滚

```powershell
python -m client.cli reboot --health-fail
```

输出：
```
重启: 从槽位 A 切换到 B
[WARN] 启动失败，剩余尝试次数: 2
```

```powershell
python -m client.cli reboot --health-fail
```

输出：
```
重启: 继续使用槽位 B
[WARN] 启动失败，剩余尝试次数: 1
```

```powershell
python -m client.cli reboot --health-fail
```

输出：
```
重启: 继续使用槽位 B
[ROLLBACK] 启动失败次数耗尽，已回滚到槽位 A
```

#### 步骤 4：确认回滚成功

```powershell
python -m client.cli status
```

输出：
```
=== 设备 A/B 状态 ===
  当前槽位:   A
  待切换槽位: 无
  启动成功:   是
  剩余尝试:   0
  槽位 A 版本: 1.0.0
  槽位 B 版本: 2.0.0
```

**回滚成功！已回到槽位 A，版本 1.0.0。**

---

## 运行自动化测试

```powershell
python -m pytest tests/ -v
```

应输出：
```
tests/test_ota.py::test_successful_upgrade PASSED
tests/test_ota.py::test_signature_verification_fails PASSED
tests/test_ota.py::test_sha256_mismatch PASSED
tests/test_ota.py::test_idempotent_state_update PASSED
tests/test_ota.py::test_rollback_on_boot_failure PASSED
tests/test_ota.py::test_device_init PASSED
tests/test_ota.py::test_duplicate_artifact_registration PASSED

7 passed
```

---

## 重置项目

如果需要从头开始，删除以下文件后重启服务器：

```powershell
# 删除数据库
Remove-Item -Force ota.db

# 删除设备状态
Remove-Item -Recurse -Force client\device_state\*

# 重启服务器
# Ctrl+C 停掉后重新运行
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

---

## 流程总览

```
┌─────────────────────────────────────────────────────┐
│                    服务器端                          │
│  uvicorn server.main:app                            │
│  ├─ POST /api/v1/admin/artifacts/register  登记工件 │
│  ├─ POST /api/v1/admin/deployments         创建部署 │
│  ├─ POST /api/v1/device/check              检查更新 │
│  ├─ GET  /api/v1/device/artifacts/{id}/manifest     │
│  ├─ PUT  /api/v1/device/installations/{id}/state    │
│  └─ GET  /repo/{type}/{ver}/{file}        下载固件  │
└─────────────────────────────────────────────────────┘
                        │
                   HTTP API
                        │
┌─────────────────────────────────────────────────────┐
│                    设备端 CLI                        │
│  python -m client.cli                               │
│  ├─ init          初始化 A/B 槽位                   │
│  ├─ check         向服务器检查更新                   │
│  ├─ apply         下载+验签+写入非活动分区           │
│  ├─ reboot        模拟重启（--health-ok / --fail）   │
│  └─ status        查看当前槽位状态                   │
└─────────────────────────────────────────────────────┘
```

```
成功升级:  init → check → apply → reboot --health-ok → status (B, v2.0.0)
回滚流程:  init → apply → reboot --health-fail ×3 → status (A, v1.0.0)
```
