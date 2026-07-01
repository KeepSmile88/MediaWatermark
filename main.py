#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

from packaging import version

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

# 确保包路径可见
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_watermarker_app.ui.main_window import MainWindow
from video_watermarker_app.ui.update_dlg import UpdateDlg
from video_watermarker_app.utils.tools import Tools

from PySide6.QtCore import Qt

def main():
    
    app = QApplication(sys.argv)
    app.setApplicationName("VideoWatermarker")
    app.setOrganizationName("SMILEY")

    qss_path = os.path.join(os.path.dirname(__file__), "video_watermarker_app/ui/styles.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    from video_watermarker_app.utils.ffmpeg_installer import FFmpegInstaller
    installer = FFmpegInstaller()
    
    from PySide6.QtWidgets import QMessageBox, QDialog
    from video_watermarker_app.ui.install_dialog import InstallDialog
    
    if not installer.is_installed():
        reply = QMessageBox.question(
            None, 
            "组件缺失", 
            "未检测到 FFmpeg 组件，是否立即自动下载并安装？\n(如果不安装，程序将无法进行视频处理)",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            dlg = InstallDialog()
            dlg.show()
            dlg.start_install() # 开始安装
            if dlg.exec() != QDialog.Accepted:
                sys.exit(0)
        else:
            sys.exit(0)

    data = Tools.get_version()
    current_ver = Tools.get_current_version()

    if data and version.parse(current_ver) < version.parse(data.get("version")):
        update_window = UpdateDlg(data)
        update_window.exec()

    try:
        win = MainWindow()
        if os.name == 'nt':
            win.setWindowIcon(QIcon("./app_icon.ico"))
        else:
            win.setWindowIcon(QIcon("./app_icon.png"))
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        from video_watermarker_app.utils.logger import logger
        logger.error(f"程序运行发生致命错误: {e}", exc_info=True)
        # 弹窗提示
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "致命错误", f"程序运行遇到问题已崩溃：\n{str(e)}\n\n详情请查看日志文件。")
        sys.exit(1)

if __name__ == "__main__":
    main()
