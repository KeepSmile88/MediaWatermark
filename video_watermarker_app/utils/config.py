#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Set
from PySide6.QtCore import QSettings

@dataclass
class WatermarkConfig:
    """单次任务的配置数据模型"""
    wm_type: str = "image"
    image_path: str = ""
    text: str = ""
    font_color: str = "#FFFFFF"
    border_color: str = "#000000"
    auto_color: bool = False
    position: str = "右下"
    custom_x: int = 20
    custom_y: int = 20
    margin: int = 20
    opacity: float = 0.8  # 0..1
    image_scale_pct: int = 15
    feather_radius: int = 0
    text_size_pct: int = 5
    font_path: str = ""
    font_name: str = ""
    same_dir: bool = True
    output_dir: str = ""
    inplace_replace: bool = False
    out_ext: str = "mp4"
    gpu_enabled: bool = False
    max_concurrent: int = 1
    crf: int = 23
    preset: str = "veryfast"

    def to_dict(self):
        return asdict(self)
        
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
                    continue
        return cls(**filtered)


class AppConfig:
    """
    全局应用配置（持久化存储），使用 QSettings。
    存储：Output Path, Last Used Values, etc.
    """
    def __init__(self):
        self.settings = QSettings("MySoft", "VideoWatermarker")

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


class HistoryManager:
    """
    管理处理历史记录，用于跳过已处理的文件。
    存储在 %APPDATA%/VideoWatermarker/history.json
    """
    def __init__(self):
        app_data = os.getenv('APPDATA') or os.path.expanduser("~")
        self.history_dir = Path(app_data) / "VideoWatermarker"
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
