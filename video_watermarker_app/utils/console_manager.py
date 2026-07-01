#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import ctypes


class ConsoleManager:
    """控制台管理器"""

    def __init__(self):
        self.console_hwnd = None
        if sys.platform == 'win32':
            self.console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            # 程序启动时隐藏控制台
            if self.console_hwnd:
                ctypes.windll.user32.ShowWindow(self.console_hwnd, 0)  # 0 = SW_HIDE

    def show_console(self):
        """显示控制台"""
        if sys.platform == 'win32' and self.console_hwnd:
            ctypes.windll.user32.ShowWindow(self.console_hwnd, 5)  # 5 = SW_SHOW
            print("控制台已显示")

    def hide_console(self):
        """隐藏控制台"""
        if sys.platform == 'win32' and self.console_hwnd:
            ctypes.windll.user32.ShowWindow(self.console_hwnd, 0)  # 0 = SW_HIDE
            print("控制台已隐藏")
