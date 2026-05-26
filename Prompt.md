你是一名资深 OTA / 嵌入式 / 后端全栈工程师。请为我生成一个“可本地运行的 A/B 分区 OTA 升级最小原型项目”，使用 Python 3.11+ 实现，要求代码完整、可执行、文件结构清晰。

目标：
1. 实现服务端 OTA API（FastAPI）：
   - POST /api/v1/admin/artifacts/register
   - POST /api/v1/admin/deployments
   - POST /api/v1/device/check
   - GET  /api/v1/device/artifacts/{artifact_id}/manifest
   - PUT  /api/v1/device/installations/{installation_id}/state
   - GET  /repo/{device_type}/{version}/{filename}
2. 实现设备端 CLI（argparse 或 typer 均可，但优先少依赖）：
   - init
   - apply
   - reboot --health-ok / --health-fail
   - status
3. 实现本地文件夹固件仓库：
   - firmware_repo/<device_type>/<version>/
   - 包含 manifest.json、manifest.sig、rootfs.img
4. 实现 build_artifact.py：
   - 计算 md5/sha256
   - 生成 manifest
   - 使用 Ed25519 对 canonical manifest 签名
5. 实现 gen_keys.py：
   - 生成 Ed25519 公私钥 PEM 文件
6. 实现简易 Web 前端：
   - 静态 HTML
   - 可以登记工件与创建部署
7. 实现本地 A/B 分区模拟：
   - client/device_state/slot_a.img
   - client/device_state/slot_b.img
   - client/device_state/boot.json
   - boot.json 包含 current_slot、pending_slot、successful、boot_attempts_left
8. 实现自动回滚模拟：
   - apply 后写入非活动槽位
   - reboot --health-ok 时 mark success
   - reboot --health-fail 且次数耗尽时回到旧槽位
9. 提供 pytest 自动化测试：
   - 成功升级
   - 签名失败
   - SHA256 不匹配
   - 重复 PUT state 幂等
   - 启动失败后回滚
10. 提供 requirements.txt、README.md、compose.yaml。

硬性约束：
- 代码必须完整，不要只给伪代码。
- 默认使用 sqlite3 保存元数据，不要引入 PostgreSQL。
- 不要把固件二进制存进数据库，只存元数据与状态。
- 所有关键状态迁移必须落盘。
- 所有文件路径使用 pathlib。
- 所有 JSON 输出 UTF-8、ensure_ascii=False。
- 签名验签必须真实可运行，不能伪造。
- 设备端接受升级的判据必须是 SHA-256 + Ed25519 签名通过，MD5 仅作为展示字段。
- API 返回值统一 JSON，错误要有 error_code 与 message。
- 代码中写清注释，说明哪些位置在真实设备上应替换为 Bootloader / 分区适配层。

完成标准：
- 按 README 中命令可以从零启动项目。
- 可以在本地完成一次从 B 升级到 A 的成功流程。
- 可以在本地完成一次升级后启动失败并自动回滚到 B 的流程。
- pytest 通过。
- README 中包含逐步操作命令。
- 项目文件树完整输出。
- 先给出计划与文件树，再逐文件输出代码。

输出方式：
- 先输出项目目录树。
- 然后按文件逐个输出代码块，文件名前用清晰标题标注。
- 最后输出 README 的完整内容与运行命令。
- 如果你发现设计缺口，请直接补全，不要停下来反问我。