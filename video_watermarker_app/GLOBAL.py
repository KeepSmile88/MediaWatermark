#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import platform


APP_NAME = "多媒体水印助手"
APP_EN_NAME = "VideoWatermarker"
APP_VER = "2.1.0"
APP_FULL_NAME = f"{APP_NAME}_V{APP_VER}"

WINDOWS_WIDTH, WINDOWS_HEIGHT = 1000, 800
X, Y = 100, 200


if os.name == 'nt':
    BASE_FOLDER = os.path.abspath(os.path.dirname(__file__))
    LOG_FOLDER = os.path.join(os.environ['appdata'], APP_NAME, "logs")
else:
    BASE_FOLDER = os.path.join(os.environ["HOME"], ".config", ".VideoWatermarker")
    LOG_FOLDER = os.path.join(os.environ['HOME'], ".config", ".VideoWatermarker", "logs")
os.makedirs(BASE_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

if os.name == 'nt':
    LOG_FILE = os.path.join(LOG_FOLDER, "app.log")
else:
    LOG_FILE = os.path.join(BASE_FOLDER, "app.log")


def get_base_dir():
    # 打包后（exe 模式）
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # 开发模式
    return os.path.dirname(os.path.abspath(__file__))

SYSTEM_NAME: str = platform.system()
if SYSTEM_NAME == "Windows":
    USER_DESKTOP = os.path.join(os.environ["USERPROFILE"], "Desktop")
    TEMP_PATH = os.environ["temp"]
elif SYSTEM_NAME == "Darwin":
    USER_DESKTOP = os.path.join(os.environ["HOME"], "Desktop")
    TEMP_PATH = "/tmp/"
elif SYSTEM_NAME == "Linux":
    USER_DESKTOP = os.path.join(os.environ["HOME"], "Desktop")
    TEMP_PATH = "/tmp/"
else:
    USER_DESKTOP = ""
    TEMP_PATH = ""

