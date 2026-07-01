#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
import hashlib
import requests
import subprocess

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from GLOBAL import APP_NAME, TEMP_PATH, BASE_FOLDER, SYSTEM_NAME, APP_VER, PLATFORM_MAP
from video_watermarker_app.utils.logger import logger
from video_watermarker_app.utils.tools import Tools
from video_watermarker_app.utils.threads import WorkerThread

from .update_window import Ui_Form as Ui_UpdateDialog


class UpdateDlg(QDialog, Ui_UpdateDialog):

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.data = data

        self.setWindowTitle("软件更新")
        if os.name == 'nt':
            self.setWindowIcon(QIcon("./app_icon.ico"))
        else:
            self.setWindowIcon(QIcon(":/images/main.icns"))
        self.resize(400, 300)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self.logger = logger

        self.filename = ""

        if SYSTEM_NAME == "Windows":
            self.temp_path = TEMP_PATH
            self.install_path = rf'C:\software\{APP_NAME}'
            self.backup_path = rf'C:\software\{APP_NAME}-bak'
            self.app_exe = rf'C:\software\{APP_NAME}\{APP_NAME}.exe'
            self.update_exe = os.path.join(BASE_FOLDER, "update.exe")

        elif SYSTEM_NAME == "Darwin":
            self.temp_path = TEMP_PATH
            self.install_path = f"/Applications/{APP_NAME}.app"
            self.backup_path = f"/Applications/{APP_NAME}-bak"
            self.app_exe = f"/Applications/{APP_NAME}.app/Contents/MacOS/{APP_NAME}"
            self.update_exe = os.path.join(BASE_FOLDER, "update.app")

        elif SYSTEM_NAME == "Linux":
            self.temp_path = TEMP_PATH
            self.install_path = os.path.expanduser(f"~/.local/bin/{APP_NAME}")
            self.backup_path = os.path.expanduser(f"~/.local/bin/{APP_NAME}-bak")
            self.app_exe = os.path.expanduser(f"~/.local/bin/{APP_NAME}/{APP_NAME}.AppImage")
            self.update_exe = None

        self.init_ui()

    def init_ui(self):

        self.btn_update.clicked.connect(self.func_update)
        self.btn_cancel.clicked.connect(self.close)

        self.download_progress.setValue(0)

        self.lab_current_ver.setText(f"\t当前版本：{APP_VER}")
        self.lab_new_ver.setText(f"\t最新版本：{self.data.get('version')}")

        # self.data["changelog"] += "\n\t- 修复了若干错误\n\t- 改进了用户界面\n\t- 增加了新功能"

        self.lab_update_content.setText(f"""
    更新内容：
        {self.data.get('changelog')}
        """)

    def func_update(self):
        self.logger.info("更新软件...")

        url_key, name_key = PLATFORM_MAP.get(SYSTEM_NAME, (None, None))
        if not url_key:
            self.show_message(f"暂不支持当前平台：{SYSTEM_NAME}")
            return

        url = self.data.get(url_key)
        filename = self.data.get(name_key)

        self.logger.debug(f"url: {url}  filename: {filename}")

        if not (url and filename):
            self.logger.error(f"自动更新失败！url={url}  filename={filename}")
            self.show_message("自动更新失败，请联系技术人员！")
            self.close()
            return
        self.filename = filename
        self._start_download(url, filename)

    def _start_download(self, url, filename):
        self.setDisabled(True)
        self.download_work = WorkerThread(self._task_download, url, filename)
        self.download_work.progress.connect(self.update_progress)
        self.download_work.max_progress.connect(self.set_max_progress)
        self.download_work.completed.connect(self._on_download_complete)
        self.download_work.start()

    def _task_download(self, url, filename):
        return self._download_from_github(url, filename)

    def _download_from_github(self, url: str, filename: str) -> bool:
        filepath = os.path.join(self.temp_path, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            self.logger.info("已删除旧版升级文件")

        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get("Content-Length", 0))
            self.logger.debug(f"文件大小：{total_size} 字节")
            if total_size:
                self.download_work.max_progress.emit(total_size)

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
                        self.download_work.progress.emit(len(chunk))

            self.logger.info("下载完成")
            return True

        except Exception as e:
            self.logger.error(f"下载失败：{e}")
            return False

    def _on_download_complete(self, success: bool):
        self.setDisabled(False)

        if not success:
            self.logger.error("下载新版本失败！")
            self.show_message("下载新版本失败，请联系技术人员！")
            self.close()
            return

        filepath = os.path.join(self.temp_path, self.filename)
        self.logger.info(f"下载完成，开始安装：{filepath}")

        try:
            if SYSTEM_NAME == "Windows":
                self._install_windows(filepath)
            elif SYSTEM_NAME == "Darwin":
                self._install_macos(filepath)
            elif SYSTEM_NAME == "Linux":
                self._install_linux(filepath)
        except Exception as e:
            self.logger.error(f"安装失败：{e}")
            self.show_message(f"安装失败：{e}")

    def _install_windows(self, filepath: str):
        """启动 Inno Setup 安装程序，静默安装后自动重启。"""
        self.logger.info("Windows：启动安装程序...")
        self.show_message("下载完成，即将启动安装程序，应用将自动重启。")
        # /SILENT 静默安装；/RESTARTAPPLICATIONS 安装完自动重启
        subprocess.Popen([filepath, "/SILENT", "/RESTARTAPPLICATIONS"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.close()

    def _install_macos(self, dmg_path: str):
        """挂载 DMG → 备份 → 替换 → 卸载 → 重启。"""
        mount_point = f"/Volumes/{APP_NAME}"
        self.logger.info("macOS：挂载 DMG...")

        subprocess.run(["hdiutil", "attach", dmg_path,
                        "-mountpoint", mount_point], check=True)
        try:
            self._backup(self.install_path, self.backup_path)
            app_src = os.path.join(mount_point, f"{APP_NAME}.app")
            self._replace(app_src, self.install_path)
            subprocess.run(["hdiutil", "detach", mount_point], check=True)
            self._restart_app()
        except Exception as e:
            self.logger.error(f"macOS 安装失败：{e}")
            self._rollback()
            raise

    def _install_linux(self, appimage_path: str):
        """替换 AppImage 文件并重启。"""
        self.logger.info("Linux：替换 AppImage...")
        self._backup(self.install_path, self.backup_path)
        try:
            dest = self.app_exe
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(appimage_path, dest)
            os.chmod(dest, 0o755)  # 确保可执行权限
            self._restart_app()
        except Exception as e:
            self.logger.error(f"Linux 安装失败：{e}")
            self._rollback()
            raise

    def _backup(self, src: str, dst: str):
        if os.path.exists(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            self.logger.info(f"备份完成：{dst}")

    def _replace(self, src: str, dst: str):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        self.logger.info("版本替换完成")

    def _rollback(self):
        if os.path.exists(self.backup_path):
            if os.path.exists(self.install_path):
                shutil.rmtree(self.install_path)
            shutil.copytree(self.backup_path, self.install_path)
            self.logger.info("已回滚到备份版本")

    def _restart_app(self):
        self.logger.info("重启应用...")
        try:
            if SYSTEM_NAME == "Windows":
                subprocess.run(["taskkill", "/IM", f"{APP_NAME}.exe", "/F"],
                               check=True)
                subprocess.Popen([self.app_exe])
            elif SYSTEM_NAME == "Darwin":
                subprocess.run(["pkill", "-f", APP_NAME], check=True)
                subprocess.Popen([self.app_exe])
            elif SYSTEM_NAME == "Linux":
                subprocess.run(["pkill", "-f", APP_NAME])
                subprocess.Popen([self.app_exe])
            self.logger.info("重启成功")
        except Exception as e:
            self.logger.error(f"重启失败：{e}")
            raise

    def set_max_progress(self, value):
        self.download_progress.setMaximum(value)

    def update_progress(self, value):
        self.download_progress.setValue(self.download_progress.value() + value)

    def show_message(self, message):
        QMessageBox.warning(self, "提示", message)
