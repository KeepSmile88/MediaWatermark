#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import sys
import time
import logging
import signal
import traceback
import threading

import logging.handlers

from functools import wraps

APP_NAME = "多媒体水印助手"

if os.name == 'nt':
    LOG_FOLDER = os.path.join(os.environ['appdata'], APP_NAME, "logs")
    os.makedirs(LOG_FOLDER, exist_ok=True)
    LOG_FILE = os.path.join(LOG_FOLDER, "app.log")
else:
    BASE_FOLDER = os.path.join(os.environ["HOME"], ".config", ".VideoWatermarker")
    os.makedirs(BASE_FOLDER, exist_ok=True)
    LOG_FILE = os.path.join(BASE_FOLDER, "app.log")


class Logger:

    def __init__(self, log_file=LOG_FILE):

        self.log_file = log_file

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        # file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler = logging.handlers.RotatingFileHandler(self.log_file, mode="a", encoding='utf-8',
                                                            maxBytes=10485760, backupCount=3)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter('%(asctime)s:\t%(levelname)s\t%(message)s\t(Line: %(lineno)d [%(filename)s])')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # 自定义异常
        sys.excepthook = self.exception_hook
        signal.signal(signal.SIGSEGV, self.signal_handler)
        signal.signal(signal.SIGABRT, self.signal_handler)
        signal.signal(signal.SIGFPE, self.signal_handler)
        signal.signal(signal.SIGILL, self.signal_handler)

    def exception_hook(self, exc_type, exc_value, exc_traceback):
        """自定义未捕获异常处理函数"""
        if issubclass(exc_type, KeyboardInterrupt):
            # 忽略用户中断
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # 使用 traceback 格式化异常信息
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print("未捕获的异常:\t", tb_str)
        self.logger.critical("未捕获的异常:\n%s", tb_str)

    def signal_handler(self, signum, frame):
        """信号处理函数，用于捕获程序崩溃信号"""
        # 获取当前线程的堆栈信息
        thread_info = threading.current_thread().name
        tb_str = ''.join(traceback.format_stack())

        self.logger.error(f"捕获到信号 {signum} ({signal.Signals(signum).name})，程序崩溃")
        self.logger.error(f"线程信息: {thread_info}")
        self.logger.error(f"堆栈信息:\n{tb_str}")

        sys.exit(1)

    def get_logger(self):
        return self.logger


    def log_exeptions(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                tb_str = traceback.format_exc()
                self.logger.error("捕获到异常：\n%s", tb_str)
                raise
        return wrapper


class Updater:
    def __init__(self, install_path, new_version_path, backup_path, main_exe):
        self.install_path = install_path
        self.new_version_path = new_version_path
        self.backup_path = backup_path
        self.main_exe = main_exe
        self.app_name = APP_NAME
        self.logger = Logger(LOG_FILE).get_logger()

    def backup_current_version(self):
        """备份当前版本"""
        self.logger.debug(f"update install path:{self.install_path} \t{self.backup_path}")
        if os.path.exists(self.install_path):
            if os.path.exists(self.backup_path):
                shutil.rmtree(self.backup_path)
                self.logger.info("旧版备份删除完成！")
            try:
                shutil.copytree(self.install_path, self.backup_path, dirs_exist_ok=True)
                print("备份完成")
                self.logger.info("备份完成！")
            except Exception as e:
                self.logger.error(f"备份失败\t{e}")

    def replace_version(self):
        """替换为新版本"""
        try:
            # if os.path.exists(self.install_path):
            #     shutil.rmtree(self.install_path)
            os.makedirs(self.install_path, exist_ok=True)
            shutil.copytree(self.new_version_path, self.install_path, dirs_exist_ok=True)
            print("替换完成")
            self.logger.info("替换完成！")
        except Exception as e:
            self.logger.error(f"替换新文件出错了：{e}")

    def install_from_dmg(self, dmg_path):
        mount_point = f"/Volumes/{self.app_name}"

        # 挂载 DMG 文件
        subprocess.run(["hdiutil", "attach", dmg_path, "-mountpoint", mount_point], check=True)

        try:
            # 备份当前版本
            self.backup_current_version()

            # 替换旧版本
            app_source_path = os.path.join(mount_point, f"{self.app_name}.app")
            self.replace_version()

            # 卸载 DMG 文件
            subprocess.run(["hdiutil", "detach", mount_point], check=True)

            # 重启应用程序
            self.restart_software()
        except Exception as e:
            print(f"安装过程发生错误: {e}")
            self.logger.error(f"安装过程发生错误: {e}")
            self.rollback_version()
            raise

    def rollback_version(self):
        if os.path.exists(self.install_path):
            shutil.rmtree(self.install_path)
        shutil.copytree(self.backup_path, self.install_path, dirs_exist_ok=True)
        self.logger.info("回滚到备份版本完成")

    def restart_software(self):
        """重启软件"""
        try:
            if sys.platform == 'win32':
                # Windows 下重新启动
                subprocess.Popen([self.main_exe])
            elif sys.platform == 'darwin':
                # macOS 下重新启动
                subprocess.Popen(["open", "-a", self.main_exe])
            print("软件重启成功")
            self.logger.info("软件重启成功")
        except Exception as e:
            print(f"重启软件时发生错误: {e}")
            self.logger.error(f"重启软件时发生错误: {e}")

    def close_software(self):
        """关闭当前正在运行的软件"""
        try:
            if sys.platform == 'win32':
                subprocess.run(["taskkill", "/IM", os.path.basename(self.main_exe), "/F"], check=True)
            elif sys.platform == 'darwin':
                subprocess.run(["pkill", "-f", os.path.basename(self.main_exe)], check=True)
            print("软件关闭成功")
            self.logger.info("软件关闭成功")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"关闭软件时发生错误，进程不存在: {e}")
        except Exception as e:
            print(f"关闭软件时发生错误: {e}")
            self.logger.error(f"关闭软件时发生错误: {e}")

    def perform_update(self):
        """执行完整的更新操作"""
        if os.name == 'nt':
            self.close_software()
            time.sleep(1)  # 等待主程序完全关闭
            self.backup_current_version()
            time.sleep(1)
            self.replace_version()
            time.sleep(1)
            self.restart_software()
        else:
            self.close_software()
            time.sleep(1)
            self.install_from_dmg(f'/tmp/{APP_NAME}.dmg')

        self.logger.info("更新程序结束！")
        print("\n\n")

if __name__ == '__main__':

    if os.name == 'nt':
        default_install_path = f"C:/software/{APP_NAME}"
        default_backup_path = f"C:/software/{APP_NAME}-bak"
        default_main_exe = f"{default_install_path}/{APP_NAME}.exe"
        default_new_ver = os.path.join(os.environ.get("temp", ""), APP_NAME, APP_NAME)
    else:
        default_install_path = f"/Applications/{APP_NAME}.app"
        default_backup_path = f"/Applications/{APP_NAME}-bak.app"
        default_main_exe = default_install_path
        default_new_ver = f"/tmp/{APP_NAME}/{APP_NAME}.app"

    # 使用示例
    updater = Updater(
        install_path=default_install_path,
        new_version_path=default_new_ver,
        backup_path=default_backup_path,
        main_exe=default_main_exe
    )
    updater.perform_update()
