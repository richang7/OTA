"""A/B 分区管理器 —— 模拟双槽位启动与回滚逻辑。

在真实设备上，此模块替换为 Bootloader 适配层（如 U-Boot env / GRUB bootset）。
boot.json 模拟 Bootloader 环境变量，slot_a/slot_b.img 模拟分区镜像。
"""

import json
import shutil
from pathlib import Path
from typing import Optional

# 默认设备状态目录
DEFAULT_STATE_DIR = Path(__file__).resolve().parent / "device_state"

# 最大启动尝试次数
MAX_BOOT_ATTEMPTS = 3


class BootConfig:
    """boot.json 的数据结构。"""

    def __init__(self, data: dict):
        self.current_slot: str = data.get("current_slot", "a")
        self.pending_slot: Optional[str] = data.get("pending_slot")
        self.successful: bool = data.get("successful", True)
        self.boot_attempts_left: int = data.get("boot_attempts_left", 0)

    def to_dict(self) -> dict:
        return {
            "current_slot": self.current_slot,
            "pending_slot": self.pending_slot,
            "successful": self.successful,
            "boot_attempts_left": self.boot_attempts_left,
        }


class ABManager:
    """A/B 分区管理器。"""

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.boot_json_path = self.state_dir / "boot.json"
        self.slot_a_path = self.state_dir / "slot_a.img"
        self.slot_b_path = self.state_dir / "slot_b.img"

    # ─── 读取/写入 boot.json ───

    def read_boot_config(self) -> BootConfig:
        """读取 boot.json，不存在则创建默认配置。"""
        if not self.boot_json_path.exists():
            cfg = BootConfig({"current_slot": "a", "pending_slot": None, "successful": True, "boot_attempts_left": 0})
            self._write_boot_config(cfg)
            return cfg
        data = json.loads(self.boot_json_path.read_text(encoding="utf-8"))
        return BootConfig(data)

    def _write_boot_config(self, cfg: BootConfig) -> None:
        """落盘 boot.json —— 所有关键状态迁移必须落盘。"""
        self.boot_json_path.write_text(
            json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ─── 槽位操作 ───

    def get_active_slot(self) -> str:
        """获取当前活动槽位。"""
        cfg = self.read_boot_config()
        return cfg.current_slot

    def get_inactive_slot(self) -> str:
        """获取非活动槽位。"""
        cfg = self.read_boot_config()
        return "b" if cfg.current_slot == "a" else "a"

    def get_slot_path(self, slot: str) -> Path:
        """获取槽位镜像路径。"""
        return self.slot_a_path if slot == "a" else self.slot_b_path

    def write_to_slot(self, slot: str, source: Path) -> None:
        """将固件写入指定槽位。

        在真实设备上，此处应替换为 dd / flash 操作写入对应分区。
        """
        dst = self.get_slot_path(slot)
        shutil.copy2(source, dst)
        # 写入版本标记
        version_file = self.state_dir / f"slot_{slot}_version.txt"
        # 尝试从固件文件名推断版本，否则标记为 unknown
        version_file.write_text(source.stem, encoding="utf-8")

    def get_slot_version(self, slot: str) -> str:
        """获取槽位固件版本。"""
        version_file = self.state_dir / f"slot_{slot}_version.txt"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()
        return "unknown"

    def apply_update(self, firmware_path: Path, version: str) -> str:
        """应用更新：写入非活动槽位，设置 pending_slot。

        返回目标槽位标识。
        在真实设备上，此处应替换为写入非活动分区 + 设置 Bootloader 启动标志。
        """
        inactive = self.get_inactive_slot()
        self.write_to_slot(inactive, firmware_path)

        # 写入版本标记
        version_file = self.state_dir / f"slot_{inactive}_version.txt"
        version_file.write_text(version, encoding="utf-8")

        cfg = self.read_boot_config()
        cfg.pending_slot = inactive
        cfg.successful = False
        cfg.boot_attempts_left = MAX_BOOT_ATTEMPTS
        self._write_boot_config(cfg)

        return inactive

    def reboot_health_ok(self) -> BootConfig:
        """启动健康 —— 标记当前槽位为成功，清除 pending。

        在真实设备上，此处由应用层调用 Bootloader 的 mark-success 命令。
        """
        cfg = self.read_boot_config()
        cfg.successful = True
        cfg.pending_slot = None
        cfg.boot_attempts_left = 0
        self._write_boot_config(cfg)
        return cfg

    def reboot_health_fail(self) -> BootConfig:
        """启动失败 —— 减少尝试次数，次数耗尽则回滚到旧槽位。

        在真实设备上，此处由 Bootloader watchdog 触发。
        """
        cfg = self.read_boot_config()
        cfg.boot_attempts_left -= 1

        if cfg.boot_attempts_left <= 0:
            # 回滚：切回旧槽位
            # pending_slot 是新固件所在槽位，current_slot 是旧槽位
            # 如果当前已经在 pending_slot 上（说明已经切换过），则切回
            if cfg.pending_slot and cfg.current_slot == cfg.pending_slot:
                # 当前在新槽位，需要回滚到旧槽位
                old_slot = "b" if cfg.current_slot == "a" else "a"
                cfg.current_slot = old_slot
            cfg.pending_slot = None
            cfg.successful = True
            cfg.boot_attempts_left = 0

        self._write_boot_config(cfg)
        return cfg

    def switch_to_pending(self) -> BootConfig:
        """切换到 pending 槽位（模拟重启后 Bootloader 切换）。

        在真实设备上，Bootloader 读取 pending_slot 标志后自动切换。
        """
        cfg = self.read_boot_config()
        if cfg.pending_slot:
            cfg.current_slot = cfg.pending_slot
            self._write_boot_config(cfg)
        return cfg

    def init_slots(self, initial_version: str = "1.0.0") -> None:
        """初始化 A/B 槽位（模拟出厂设置）。"""
        # 创建空镜像文件
        self.slot_a_path.write_bytes(b"SLOT_A_INITIAL")
        self.slot_b_path.write_bytes(b"SLOT_B_INITIAL")

        # 版本标记
        (self.state_dir / "slot_a_version.txt").write_text(initial_version, encoding="utf-8")
        (self.state_dir / "slot_b_version.txt").write_text("empty", encoding="utf-8")

        # boot.json
        cfg = BootConfig({
            "current_slot": "a",
            "pending_slot": None,
            "successful": True,
            "boot_attempts_left": 0,
        })
        self._write_boot_config(cfg)
