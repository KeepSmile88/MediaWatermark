#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import requests

from .logger import logger
from GLOBAL import UPDATE_URL, APP_NAME, APP_VER


class Tools():

    def __init__(self, data):
        self.data = data

    def is_chinese(self, name):
        """检查是否包含中文字符"""
        pattern = re.compile(r'[\u4e00-\u9fff]+')
        return bool(pattern.search(name))

    def is_english(self, name):
        """检查是否仅包含英文字母和空格"""
        pattern = re.compile(r'^[a-zA-Z\s]+$')
        return bool(pattern.match(name))

    @staticmethod
    def check_path_valid(fp):
        try:
            if os.path.exists(fp):
                return True
        except Exception as e:
            print("check_path_valid error:", e)
            return False

        return False

    @staticmethod
    def get_current_version():
        return APP_VER

    @staticmethod
    def get_version() -> dict:
        data = {}

        try:
            response = requests.get(UPDATE_URL, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"自动更新获取失败：{e}")
            return data

        raw = response.json()
        assets = raw.get("assets", [])
        win_asset = next((a for a in assets if a["name"].endswith(".exe")), None)
        mac_asset = next((a for a in assets if a["name"].endswith(".dmg")), None)
        linux_asset = next((a for a in assets if a["name"].endswith(".AppImage")), None)

        data["version"] = raw.get("tag_name", "").lstrip("v")
        data["changelog"] = raw.get("body", "")

        data["download_url_win"] = win_asset["browser_download_url"] if win_asset else None
        data["filename_win"] = win_asset["name"] if win_asset else None

        data["download_url_mac"] = mac_asset["browser_download_url"] if mac_asset else None
        data["filename_mac"] = mac_asset["name"] if mac_asset else None

        data["download_url_linux"] = linux_asset["browser_download_url"] if linux_asset else None
        data["filename_linux"] = linux_asset["name"] if linux_asset else None

        return data
