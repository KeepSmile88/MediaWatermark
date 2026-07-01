#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import hashlib
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Set, List
from PySide6.QtCore import QSettings

from GLOBAL import APP_EN_NAME

@dataclass
class WatermarkConfig:
    """单次任务的配置数据模型"""
    wm_type: str = "text"  # "image" | "text"
    image_path: str = ""
    text: str = "Generat cu AI"
    font_color: str = "#FFFFFF"  # 新增：文字颜色
    border_color: str = "#000000"  # 描边颜色
    auto_color: bool = True  # 智能选色
    bg_enabled: bool = False  # 是否启用水印背景色
    bg_color: str = "#000000"  # 水印背景颜色
    position: str = "右上"  # 左上/右上/左下/右下/居中/自定义
    custom_x: int = 20
    custom_y: int = 20
    center_y_offset: int = 0  # 居中位置时的垂直偏移（正值下移，负值上移）
    margin: int = 20
    opacity: float = 0.8  # 0..1
    image_scale_pct: int = 2  # watermark width as % of video width
    feather_radius: int = 0    # 0-20 px blurring for image edges
    text_size_pct: int = 5     # font size as % of video height
    font_path: str = ""        # path to custom font file
    font_name: str = ""        # display name of font
    same_dir: bool = True
    output_dir: str = ""
    inplace_replace: bool = False  # 新增：原地替换原文件
    out_ext: str = "mp4"       # mp4/mkv...
    gpu_enabled: bool = False  # Enable hardware acceleration
    max_concurrent: int = 1    # Max parallel tasks
    crf: int = 23
    preset: str = "veryfast"
    lossless_image: bool = False  # 全保真处理图片
    # 高级模式：额外水印层（不参与标准序列化，单独管理）
    extra_watermarks: list = field(default_factory=list)
    
    # 将 dataclass 转为 dict（不包含 extra_watermarks，它单独序列化）
    def to_dict(self):
        d = asdict(self)
        d.pop('extra_watermarks', None)
        return d
        
    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict):
            return cls()

        annotations = cls.__annotations__
        filtered = {}
        for k, v in data.items():
            if k in annotations and v is not None:
                target_type = annotations[k]
                try:
                    # 类型强制转换逻辑
                    if target_type == bool:
                        if isinstance(v, str):
                            filtered[k] = v.lower() in ("true", "1", "yes")
                        else:
                            filtered[k] = bool(v)
                    elif target_type == int:
                        filtered[k] = int(v)
                    elif target_type == float:
                        filtered[k] = float(v)
                    elif target_type == str:
                        filtered[k] = str(v)
                    else:
                        filtered[k] = v
                except (ValueError, TypeError):
                    # 转换失败则忽略，使用默认值
                    continue
        return cls(**filtered)


class AppConfig:
    """
    全局应用配置（持久化存储），使用 QSettings。
    存储：Output Path, Last Used Values, etc.
    """
    def __init__(self):
        # Organization Name, Application Name
        self.settings = QSettings("SMILEY", APP_EN_NAME)

    def load_last_config(self) -> WatermarkConfig:
        """从 QSettings 加载上次的配置，如果没有则返回默认值"""
        data_json = self.settings.value("last_config_json", "{}")
        if isinstance(data_json, str):
            try:
                data = json.loads(data_json)
                return WatermarkConfig.from_dict(data)
            except Exception:
                pass
        return WatermarkConfig()

    def save_last_config(self, cfg: WatermarkConfig):
        """保存当前配置供下次使用"""
        data = cfg.to_dict()
        self.settings.setValue("last_config_json", json.dumps(data))

    def get(self, key: str, default=None):
        return self.settings.value(key, default)

    def set(self, key: str, value):
        self.settings.setValue(key, value)

    def get_last_template_name(self) -> str:
        """获取上次使用的模板名称"""
        return self.settings.value("last_template_name", "")

    def set_last_template_name(self, name: str):
        """保存当前选中的模板名称"""
        self.settings.setValue("last_template_name", name)

    def get_templates(self) -> dict:
        """获取所有已保存的模板"""
        val = self.settings.value("templates_json", "{}")
        if isinstance(val, dict):
            return val
        if not isinstance(val, str):
            return {}
        try:
            return json.loads(val)
        except Exception:
            return {}

    def save_template(self, name: str, cfg: WatermarkConfig):
        """保存一个新模板"""
        templates = self.get_templates()
        templates[name] = cfg.to_dict()
        self.settings.setValue("templates_json", json.dumps(templates))

    def delete_template(self, name: str):
        """删除一个模板"""
        templates = self.get_templates()
        if name in templates:
            del templates[name]
            self.settings.setValue("templates_json", json.dumps(templates))

    # --- 高级模式管理 ---
    _DEFAULT_PASSWORD = "admin123"

    def is_advanced_mode(self) -> bool:
        """检查高级模式是否已激活"""
        return self.settings.value("advanced_mode", False, type=bool)

    def set_advanced_mode(self, enabled: bool):
        """设置高级模式状态"""
        self.settings.setValue("advanced_mode", enabled)

    def _hash_password(self, password: str, salt: bytes = None) -> str:
        """使用 PBKDF2 安全哈希密码"""
        import os, binascii
        if salt is None:
            salt = os.urandom(16)
        # PBKDF2 with HMAC-SHA256, 100,000 iterations
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        # 存储格式：salt + hash，全部转为 hex
        return binascii.hexlify(salt + dk).decode('ascii')

    def get_advanced_password_hash(self) -> str:
        """获取存储的密码哈希值，如果没有则返回默认密码的哈希"""
        stored = self.settings.value("advanced_password_hash", "")
        if not stored:
            # 默认密码的哈希值也应该使用安全的 PBKDF2，但为了避免每次生成不同的 salt 导致问题，
            # 实际上默认密码仅在未设置时有效，所以我们在此固定一个静态盐值用于默认密码（仅用于比较）
            static_salt = b'default_salt_123'
            return self._hash_password(self._DEFAULT_PASSWORD, static_salt)
        return stored

    def verify_advanced_password(self, password: str) -> bool:
        """验证高级模式密码"""
        import binascii
        stored = self.get_advanced_password_hash()
        try:
            # 尝试按新格式解析（hex 长度应该 >= 32，前16字节是salt也就是32个hex字符）
            raw = binascii.unhexlify(stored)
            if len(raw) > 16:
                salt = raw[:16]
                dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
                return raw[16:] == dk
        except Exception:
            pass
        
        # 向后兼容：旧版本简单的 SHA-256
        old_hash = hashlib.sha256(password.encode()).hexdigest()
        return old_hash == stored

    def set_advanced_password(self, new_password: str):
        """修改高级模式密码"""
        pw_hash = self._hash_password(new_password)
        self.settings.setValue("advanced_password_hash", pw_hash)

    def save_extra_watermarks(self, configs: list):
        """保存额外水印层配置列表"""
        data = [c.to_dict() if hasattr(c, 'to_dict') else c for c in configs]
        self.settings.setValue("extra_watermarks_json", json.dumps(data))

    def load_extra_watermarks(self) -> list:
        """加载额外水印层配置列表"""
        val = self.settings.value("extra_watermarks_json", "[]")
        if not isinstance(val, str):
            return []
        try:
            data = json.loads(val)
            if isinstance(data, list):
                return [WatermarkConfig.from_dict(d) for d in data]
        except Exception:
            pass
        return []


class HistoryManager:
    """
    管理处理历史记录，用于跳过已处理的文件。
    存储在 %APPDATA%/VideoWatermarker/history.json
    """
    def __init__(self):
        app_data = os.getenv('APPDATA') or os.path.expanduser("~")
        self.history_dir = Path(app_data) / APP_EN_NAME
        self.history_file = self.history_dir / "history.json"
        self._history: Set[str] = set()
        self._lock = threading.Lock()
        self.load()

    def load(self):
        """从文件加载历史记录"""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._history = set(data)
            except Exception:
                self._history = set()

    def save(self):
        """保存历史记录到文件"""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                with open(self.history_file, "w", encoding="utf-8") as f:
                    json.dump(list(self._history), f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def is_processed(self, file_path: str) -> bool:
        """检查文件是否已处理过"""
        abs_path = os.path.abspath(file_path)
        with self._lock:
            return abs_path in self._history

    def add_record(self, file_path: str):
        """添加一条处理记录"""
        abs_path = os.path.abspath(file_path)
        with self._lock:
            self._history.add(abs_path)
        self.save()

    def clear(self):
        """清空历史记录"""
        with self._lock:
            self._history.clear()
        if self.history_file.exists():
            try:
                os.remove(self.history_file)
            except Exception:
                pass
