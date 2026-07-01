#! /usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox
)
from video_watermarker_app.utils.ffmpeg_installer import FFmpegInstaller


class InstallThread(QThread):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, installer):
        super().__init__()
        self.installer = installer

    def run(self):
        def callback(p, msg):
            self.progress.emit(p, msg)
        
        success = self.installer.install(callback)
        if success:
            self.finished.emit(True, "安装成功")
        else:
            self.finished.emit(False, "安装失败，请检查网络或手动安装")


class InstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("依赖组件安装")
        self.setFixedSize(400, 150)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.lbl_msg = QLabel("正在检测系统环境...", self)
        layout.addWidget(self.lbl_msg)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.installer = FFmpegInstaller()
        self.thread = InstallThread(self.installer)
        self.thread.progress.connect(self._on_progress)
        self.thread.finished.connect(self._on_finished)

    def start_install(self):
        self.lbl_msg.setText("准备下载 FFmpeg...")
        self.thread.start()

    def _on_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.lbl_msg.setText(msg)

    def _on_finished(self, success, msg):
        if success:
            self.accept()
        else:
            QMessageBox.critical(self, "错误", msg)
            self.reject()
