#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import copy
import shutil
import subprocess
import tempfile
from packaging import version

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QMovie, QIcon, QAction, QPixmap, QPainter, QColor, QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QTableWidgetItem, QHeaderView, QLabel, QMessageBox, QWidget, QProgressBar,
    QTabWidget, QInputDialog, QMenu
)

from video_watermarker_app.ui.ui_mainwindow import Ui_MainWindow
from video_watermarker_app.ui.settings_dialog import SettingsDialog
from video_watermarker_app.ui.help_dialog import HelpDialog
from video_watermarker_app.ui.update_dlg import UpdateDlg
from video_watermarker_app.ui.video_splitter_widget import VideoSplitterWidget
from video_watermarker_app.ui.video_merger_widget import VideoMergerWidget
from video_watermarker_app.ui.picture_splitter_widget import PictureSplitterWidget
from video_watermarker_app.ui.text_recolor_widget import TextRecolorWidget
from video_watermarker_app.core.ffmpeg_worker import WatermarkWorker
from video_watermarker_app.utils.config import AppConfig, WatermarkConfig
from video_watermarker_app.utils.common import (
    is_video_file, is_image_file, check_ffmpeg, to_ffmpeg_filter_path, default_font_path, calc_auto_font_size,
    get_sp_kwargs
)
from video_watermarker_app.utils.logger import logger
from video_watermarker_app.utils.console_manager import ConsoleManager
from video_watermarker_app.utils.tools import Tools

from GLOBAL import APP_NAME, APP_FULL_NAME, APP_VER


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle(APP_FULL_NAME)

        self.tabWidget = QTabWidget()
        self.video_splitter = VideoSplitterWidget()
        self.video_merger = VideoMergerWidget()
        self.picture_splitter = PictureSplitterWidget()
        self.text_recolor = TextRecolorWidget()

        self.tabWidget.addTab(self.centralwidget, "视频水印")
        self.tabWidget.addTab(self.video_splitter, "视频分割")
        self.tabWidget.addTab(self.video_merger, "视频合成")
        self.tabWidget.addTab(self.picture_splitter, "图片分割")
        self.tabWidget.addTab(self.text_recolor, "文字变色")

        self.setCentralWidget(self.tabWidget)
        self.app_config = AppConfig()
        self.current_cfg = self.app_config.load_last_config()

        # 同步水印配置到视频分割面板
        self.video_splitter.set_watermark_config(self.current_cfg)
        # 同步水印配置到视频合成面板
        self.video_merger.set_watermark_config(self.current_cfg)

        # --- 高级模式初始化 ---
        self._advanced_mode = self.app_config.is_advanced_mode()
        if self._advanced_mode:
            self.current_cfg.extra_watermarks = self.app_config.load_extra_watermarks()

        # 初始化控制台管理器
        self.console_manager = ConsoleManager()
        
        # 显式设置预览 Label 对齐方式
        self.lblWatermarkPreview.setAlignment(Qt.AlignCenter)
        self.active_workers = {} # {idx: worker}
        self.task_queue = []     # [(idx, path)]
        self.stats = {"total": 0, "done": 0, "fail": 0, "skip": 0}
        self.current_preview_frame = None # QPixmap
        self.current_selected_path = None

        # 信号绑定
        self.btnClearWatermark.clicked.connect(self._clear_watermark)
        self.btnSelectFolder.clicked.connect(self._add_folder)
        self.btnStartProcess.clicked.connect(self._start_task)
        self.btnStop.clicked.connect(self._stop_all_tasks)
        self.btnReset.clicked.connect(self._reset_tasks)

        self.actionUpdate = QAction("检查更新")
        self.menuHelp.addSeparator()
        self.menuHelp.addAction(self.actionUpdate)
        
        self.actionSettings.triggered.connect(self._open_settings)
        self.actionClearHistory.triggered.connect(self._clear_history)
        self.actionUpdate.triggered.connect(self._show_update)
        self.actionHelp.triggered.connect(self._show_help)
        self.actionAbout.triggered.connect(self._show_about)
        self.actionExit.triggered.connect(self.close)
        self.tableFiles.itemSelectionChanged.connect(self._on_selection_changed)
        self.tableFiles.customContextMenuRequested.connect(self._on_table_context_menu)

        self.setAcceptDrops(True)
        self.lblCurrentFolder.setText("未选择文件夹")

        self.lblRightTitle.setText(APP_NAME)
        self._refresh_watermark_view()

        # --- 高级模式快捷键 Ctrl+Alt+A ---
        shortcut = QShortcut(QKeySequence("Ctrl+Alt+A"), self)
        shortcut.activated.connect(self._toggle_advanced_mode)

    def _refresh_watermark_view(self):
        """刷新左侧面板的水印预览状态"""
        # 如果没有视频帧，我们创建一个临时的背景作为虚拟画布
        if not self.current_preview_frame:
            # 创建一个 1280x720 的高清虚拟画布，方便看清位置变化
            dummy = QPixmap(1280, 720)
            dummy.fill(QColor("#1e1e1e"))
            
            # 使用 temp 变量进行渲染
            temp_frame = self.current_preview_frame
            self.current_preview_frame = dummy
            self._draw_preview_overlay()
            self.current_preview_frame = temp_frame
        else:
            self._draw_preview_overlay()
        
        # 强制更新界面
        self.lblWatermarkPreview.repaint()

    def _draw_preview_overlay(self):
        """在当前捕获的视频帧上绘制实时水印预览"""
        if not self.current_preview_frame: return
        
        # 创建画布复刻
        canvas = self.current_preview_frame.copy()
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        cfg = self.current_cfg
        opacity = cfg.opacity
        margin = cfg.margin
        
        w, h = canvas.width(), canvas.height()
        
        if cfg.wm_type == "image" and os.path.exists(cfg.image_path):
            wm_pixmap = QPixmap(cfg.image_path)
            # 计算缩放
            wm_w = int(w * (cfg.image_scale_pct / 100.0))
            wm_scaled = wm_pixmap.scaledToWidth(wm_w, Qt.SmoothTransformation)
            wm_h = wm_scaled.height()
            
            painter.setOpacity(opacity)
            
            # 计算位置
            x, y = self._get_overlay_pos(cfg.position, w, h, wm_w, wm_h, margin)
            painter.drawPixmap(x, y, wm_scaled)
            
        elif cfg.wm_type == "text" and cfg.text:
            painter.setOpacity(opacity)
            # 字体大小计算
            safe_h = max(h, 100)
            safe_w = max(w, 100)
            
            # 上中/下中位置：自动根据画面宽度和文字长度计算字号
            if cfg.position in ("上中", "下中"):
                font_size = calc_auto_font_size(cfg.text, safe_w, safe_h, margin, cfg.font_name)
            else:
                font_size = max(8, int(safe_h * (cfg.text_size_pct / 100.0)))
            
            font = QFont(cfg.font_name if cfg.font_name else "Microsoft YaHei", font_size)
            painter.setFont(font)
            
            # 使用配置中的颜色
            if not cfg.auto_color:
                text_color = QColor(cfg.font_color)
                display_text = cfg.text
            else:
                text_color = QColor("#D0DEE0") 
                display_text = f"{cfg.text} (Auto)"
            
            if not text_color.isValid(): text_color = QColor("white")
            painter.setPen(text_color)
            
            metrics = QFontMetrics(font)
            tw = metrics.horizontalAdvance(display_text)
            th = metrics.height()
            
            x, y = self._get_overlay_pos(cfg.position, w, h, tw, th, margin)
            
            # 绘制背景色块（如果启用）
            if cfg.bg_enabled and cfg.bg_color:
                bg_color = QColor(cfg.bg_color)
                if bg_color.isValid():
                    bg_color.setAlphaF(opacity)
                    painter.setBrush(bg_color)
                    painter.setPen(Qt.NoPen)
                    padding = 8
                    painter.drawRect(x - padding, y - padding, tw + padding * 2, th + padding * 2)
                    # 恢复画笔颜色
                    painter.setPen(text_color)
            
            painter.drawText(x, y + metrics.ascent(), display_text)
            
        painter.end()
        # 适应 Label 大小显示
        final = canvas.scaled(self.lblWatermarkPreview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lblWatermarkPreview.setPixmap(final)
        self.lblWatermarkPreview.update()

    def _get_overlay_pos(self, position, mw, mh, sw, sh, margin):
        # 智能避让 + 用户偏移优先
        user_offset = getattr(self.current_cfg, 'center_y_offset', 0)
        avoid_offset = self._calc_preview_avoidance(position, mh)
        
        if position == "左上": return (margin, margin)
        if position == "右上": return (mw - sw - margin, margin)
        if position == "左下": return (margin, mh - sh - margin)
        if position == "右下": return (mw - sw - margin, mh - sh - margin)
        if position == "上中":
            # 用户偏移优先：非零时用用户值（负值上移，正值下移）
            offset = abs(user_offset) if user_offset != 0 else avoid_offset
            if user_offset > 0:
                offset = max(0, avoid_offset - user_offset)
            return ((mw - sw) // 2, margin + offset)
        if position == "下中":
            offset = abs(user_offset) if user_offset != 0 else avoid_offset
            if user_offset > 0:
                offset = max(0, avoid_offset - user_offset)
            return ((mw - sw) // 2, mh - sh - margin - offset)
        if position == "居中":
            return ((mw - sw) // 2, (mh - sh) // 2 + user_offset)
        if position == "自定义": return (self.current_cfg.custom_x, self.current_cfg.custom_y)
        return (margin, margin)
    
    def _calc_preview_avoidance(self, position, canvas_h):
        """
        预览中的智能避让：检查当前水印位置是否与其他水印层存在重叠风险。
        返回需要向内偏移的像素量。
        """
        if position not in ("上中", "下中"):
            return 0
        
        cfg = self.current_cfg
        extra_wms = getattr(cfg, 'extra_watermarks', [])
        
        # 收集对应角落的水印配置（从额外层中查找）
        if position == "下中":
            corner_cfgs = [c for c in extra_wms if c.position in ("右下", "左下")]
        elif position == "上中":
            corner_cfgs = [c for c in extra_wms if c.position in ("右上", "左上")]
        else:
            return 0
        
        if not corner_cfgs:
            return 0
        
        # 估算角落水印高度
        max_h = 0
        for c in corner_cfgs:
            if c.wm_type == "text" and c.text:
                fs = max(1, int(canvas_h * (c.text_size_pct / 100.0)))
                max_h = max(max_h, int(fs * 1.4))
            elif c.wm_type == "image":
                # 简单估算
                max_h = max(max_h, int(canvas_h * 0.03))
        
        padding = max(5, int(canvas_h * 0.01))
        return max_h + padding if max_h > 0 else 0

    def _on_selection_changed(self):
        items = self.tableFiles.selectedItems()
        if not items: 
            self.current_preview_frame = None
            self.current_selected_path = None
            self._refresh_watermark_view()
            return
        
        row = items[0].row()
        path = self.tableFiles.item(row, 0).data(Qt.UserRole)
        
        if path == self.current_selected_path: return
        self.current_selected_path = path
        
        # 区分处理：图片直接加载，视频提取帧
        if is_image_file(path):
            self.current_preview_frame = QPixmap(path)
            self._draw_preview_overlay()
        else:
            self._extract_frame(path)

    def _extract_frame(self, path):
        ffmpeg, _ = check_ffmpeg()
        if not ffmpeg: return
        
        # 提取第 1 秒的帧
        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        tmp.close()
        
        cmd = [ffmpeg, "-y", "-ss", "00:00:01", "-i", path, "-frames:v", "1", "-q:v", "2", tmp.name]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=5, **get_sp_kwargs())
            self.current_preview_frame = QPixmap(tmp.name)
            self._draw_preview_overlay()
        except:
            # 失败则清除预览
            self.current_preview_frame = None
            self._refresh_watermark_view()
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def _open_settings(self):
        dlg = SettingsDialog(self, advanced_mode=self._advanced_mode)
        dlg.config_changed.connect(self._on_config_changed_live)
        if dlg.exec():
            self.current_cfg = self.app_config.load_last_config()
            # 高级模式：加载额外水印层
            if self._advanced_mode:
                extra = dlg.get_extra_watermarks()
                self.current_cfg.extra_watermarks = extra
                self.app_config.save_extra_watermarks(extra)
            self._refresh_watermark_view()
            # 同步到视频分割面板
            self.video_splitter.set_watermark_config(self.current_cfg)
            # 同步到视频合成面板
            self.video_merger.set_watermark_config(self.current_cfg)
            self.statusbar.showMessage("设置已保存", 3000)

    def _clear_history(self):
        from video_watermarker_app.utils.config import HistoryManager
        msg = "确定要清空所有处理记录吗？\n清空后之前处理过的视频将不再被自动跳过。"
        ret = QMessageBox.question(self, "确认", msg, QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            HistoryManager().clear()
            self.statusbar.showMessage("处理历史记录已清空", 3000)
            self._reset_tasks()

    def _toggle_advanced_mode(self):
        """Ctrl+Alt+A 触发：密码验证后切换高级模式"""
        if self._advanced_mode:
            # 已激活，询问是否关闭或修改密码
            ret = QMessageBox.question(
                self, "高级模式",
                '高级模式已激活。\n\n• 点击 Yes 关闭高级模式\n• 点击 No 修改密码',
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if ret == QMessageBox.Yes:
                self._advanced_mode = False
                self.app_config.set_advanced_mode(False)
                self.current_cfg.extra_watermarks = []
                self.statusbar.showMessage("🔒 高级模式已关闭", 5000)
            elif ret == QMessageBox.No:
                self._change_advanced_password()
            return

        # 未激活，弹出密码输入
        password, ok = QInputDialog.getText(
            self, "🔐 高级模式", "请输入高级功能激活密码:"
        )
        if not ok or not password:
            return

        if self.app_config.verify_advanced_password(password):
            self._advanced_mode = True
            self.app_config.set_advanced_mode(True)
            # 加载已保存的额外水印配置
            self.current_cfg.extra_watermarks = self.app_config.load_extra_watermarks()
            self.statusbar.showMessage("🔓 高级模式已激活！设置中可配置多套水印", 5000)
            QMessageBox.information(
                self, "高级模式",
                "✅ 高级模式已成功激活！\n\n"
                "现在可以在「设置」中配置最多 4 套同时生效的水印。\n"
                "再次按 Ctrl+Alt+A 可关闭高级模式或修改密码。"
            )
        else:
            QMessageBox.warning(self, "验证失败", "❌ 密码错误，无法激活高级模式。")

    def _change_advanced_password(self):
        """修改高级模式密码"""
        # 先验证旧密码
        old_pw, ok = QInputDialog.getText(
            self, "修改密码", "请输入当前密码:"
        )
        if not ok or not old_pw:
            return
        if not self.app_config.verify_advanced_password(old_pw):
            QMessageBox.warning(self, "验证失败", "当前密码错误")
            return

        # 输入新密码
        new_pw, ok = QInputDialog.getText(
            self, "修改密码", "请输入新密码:"
        )
        if not ok or not new_pw:
            return

        # 确认新密码
        confirm_pw, ok = QInputDialog.getText(
            self, "修改密码", "请再次确认新密码:"
        )
        if not ok or confirm_pw != new_pw:
            QMessageBox.warning(self, "修改失败", "两次输入的密码不一致")
            return

        self.app_config.set_advanced_password(new_pw)
        QMessageBox.information(self, "修改成功", "✅ 高级模式密码已更新")

    def _on_config_changed_live(self, cfg):
        # 实时同步配置对象
        self.current_cfg = cfg
        self.statusbar.showMessage(f"预览同步中: {cfg.wm_type} | {cfg.position}", 1000)
        self._refresh_watermark_view()
        # 同步到视频分割面板
        self.video_splitter.set_watermark_config(self.current_cfg)
        # 同步到视频合成面板
        self.video_merger.set_watermark_config(self.current_cfg)

    def _clear_watermark(self):
        self.current_cfg.image_path = ""
        self.app_config.save_last_config(self.current_cfg)
        self._refresh_watermark_view()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        pos = event.position().toPoint()
        target = self.childAt(pos)

        is_left = False
        tmp = target
        while tmp:
            if tmp == self.leftPanel:
                is_left = True
                break
            tmp = tmp.parentWidget()
        
        files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                # 递归添加视频和图片
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        if is_video_file(fp) or is_image_file(fp):
                            files.append(fp)
            else:
                if is_left and is_image_file(path):
                    # 拖到左边且是图片 -> 设置为水印
                    self.current_cfg.wm_type = "image"
                    self.current_cfg.image_path = path
                    self.app_config.save_last_config(self.current_cfg)
                    self._refresh_watermark_view()
                    self.statusbar.showMessage(f"水印图片已更新: {os.path.basename(path)}", 3000)
                    continue 
                
                if is_video_file(path) or is_image_file(path):
                    files.append(path)
        
        if files:
            self._append_files(files)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d:
            self.lblCurrentFolder.setText(os.path.basename(d))
            files = []
            for root, _, fs in os.walk(d):
                for f in fs:
                    fp = os.path.join(root, f)
                    if is_video_file(fp) or is_image_file(fp):
                        files.append(fp)
            self._append_files(files)

    def _append_files(self, files):
        existing = set()
        for r in range(self.tableFiles.rowCount()):
            existing.add(self.tableFiles.item(r, 0).data(Qt.UserRole)) # 存储全路径
            
        for f in files:
            if f not in existing:
                row = self.tableFiles.rowCount()
                self.tableFiles.insertRow(row)

                name_item = QTableWidgetItem(os.path.basename(f))
                name_item.setData(Qt.UserRole, f)
                name_item.setToolTip(f)
                
                ext = os.path.splitext(f)[1].upper().replace(".", "")
                try:
                    size_mb = os.path.getsize(f) / (1024 * 1024)
                except:
                    size_mb = 0
                
                self.tableFiles.setItem(row, 0, name_item)
                self.tableFiles.setItem(row, 1, QTableWidgetItem(ext))
                self.tableFiles.setItem(row, 2, QTableWidgetItem(f"{size_mb:.2f} MB"))
                
                # 进度条
                pbar = QProgressBar()
                pbar.setValue(0)
                pbar.setTextVisible(False)
                pbar.setFixedHeight(8)
                self.tableFiles.setCellWidget(row, 3, pbar)
                
                self.tableFiles.setItem(row, 4, QTableWidgetItem("等待中"))
        
        self._update_stats()

    def _update_stats(self):
        total = self.tableFiles.rowCount()
        done = 0
        fail = 0
        skip = 0
        for r in range(total):
            status_item = self.tableFiles.item(r, 4)
            if not status_item: continue
            txt = status_item.text()
            if "已完成" in txt: done += 1
            elif "失败" in txt: fail += 1
            elif "跳过" in txt: skip += 1
            
        self.stats = {"total": total, "done": done, "fail": fail, "skip": skip}
        
        self.statValue_Total.setText(str(total))
        self.statValue_Done.setText(str(done))
        self.statValue_Fail.setText(str(fail))
        self.statValue_Skip.setText(str(skip))
        self.lblFileCount.setText(f"{total} 个项目")

    def _reset_tasks(self):
        """重置所有状态，但不清除文件列表"""
        self.stats = {"total": self.tableFiles.rowCount(), "done": 0, "fail": 0, "skip": 0}
        for r in range(self.tableFiles.rowCount()):
            self.tableFiles.item(r, 4).setText("等待中")
            pbar = self.tableFiles.cellWidget(r, 3)
            if pbar: pbar.setValue(0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self._remove_selected_rows()
        else:
            super().keyPressEvent(event)

    def _on_table_context_menu(self, pos):
        menu = QMenu(self)
        act_remove = menu.addAction("移除选中项")
        act_clear = menu.addAction("清空全部列表")
        
        action = menu.exec(self.tableFiles.viewport().mapToGlobal(pos))
        if action == act_remove:
            self._remove_selected_rows()
        elif action == act_clear:
            self._clear_all_rows()

    def _remove_selected_rows(self):
        # 必须从后往前删，否则索引会乱
        selected_rows = sorted(set(index.row() for index in self.tableFiles.selectedIndexes()), reverse=True)
        if not selected_rows:
            return
            
        for row in selected_rows:
            self.tableFiles.removeRow(row)
        
        self.statusbar.showMessage(f"已移除 {len(selected_rows)} 个文件", 3000)
        self._update_stats()

    def _clear_all_rows(self):
        if self.tableFiles.rowCount() == 0:
            return
        ret = QMessageBox.question(self, "确认", "确定要清空文件列表吗？", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.tableFiles.setRowCount(0)
            self.statusbar.showMessage("列表已清空", 3000)
            self._update_stats()
        self._update_stats()

    def _start_task(self):
        if self.tableFiles.rowCount() == 0:
            QMessageBox.warning(self, "提示", "请先添加文件")
            return
            
        if self.current_cfg.wm_type == "image" and not os.path.exists(self.current_cfg.image_path):
             QMessageBox.warning(self, "提示", "水印图片不存在，请点击左侧区域上传")
             return

        # 获取所有待处理文件
        self.task_queue = []
        for r in range(self.tableFiles.rowCount()):
            path = self.tableFiles.item(r, 0).data(Qt.UserRole)
            status = self.tableFiles.item(r, 4).text()
            if "已完成" not in status and "已跳过" not in status:
                self.task_queue.append((r, path))
                self.tableFiles.item(r, 4).setText("等候...")
        
        if not self.task_queue:
            QMessageBox.information(self, "提示", "所有文件已处理完成")
            return

        self.btnStartProcess.setEnabled(False)
        self.btnSelectFolder.setEnabled(False)
        self.btnReset.setEnabled(False)
        self.btnStop.setEnabled(True)
        
        # 开始调度
        self._schedule_tasks()

    def _schedule_tasks(self):
        """调度器：根据并发限制启动任务"""
        try:
            max_concurrent = self.current_cfg.max_concurrent
            
            # 补充启动新任务，直到达到并发上限
            while len(self.active_workers) < max_concurrent and self.task_queue:
                idx, path = self.task_queue.pop(0)
                
                # 使用深拷贝，防止主界面修改设置时干扰正在进行的任务
                worker_cfg = copy.deepcopy(self.current_cfg)
                
                worker = WatermarkWorker(idx, path, worker_cfg)
                worker.task_started.connect(self._on_task_started)
                worker.task_progress.connect(self._on_task_progress)
                worker.task_finished.connect(self._on_task_finished)
                
                # 关键修复：不在逻辑完成时删引用，而是等待线程物理退出后再清理
                worker.finished.connect(lambda i=idx: self._on_worker_teardown(i))
                worker.finished.connect(worker.deleteLater)
                
                self.active_workers[idx] = worker
                worker.start()
            
            # 如果队列为空且没有活跃任务，则说明全部结束
            if not self.active_workers and not self.task_queue:
                self._on_all_finished()
        except Exception as e:
            logger.error(f"任务调度异常: {e}")
            self.statusbar.showMessage(f"调度出错: {e}")

    def _on_worker_teardown(self, idx):
        """线程彻底结束后的收尾工作"""
        if idx in self.active_workers:
            del self.active_workers[idx]
        # 尝试启动队列中的下一个任务
        self._schedule_tasks()

    def _stop_all_tasks(self):
        """取消所有任务"""
        self.task_queue = [] # 清空队列
        for idx, worker in self.active_workers.items():
            worker.stop()
        self.statusbar.showMessage("正在停止所有任务...")
        self.btnStop.setEnabled(False)

    def _on_task_started(self, idx, path):
        item = self.tableFiles.item(idx, 4)
        if item:
            item.setText("正在处理")
        # 多任务模式下不再强制 selectRow 以免干扰用户浏览其他行
        self.statusbar.showMessage(f"已启动任务: {os.path.basename(path)}")

    def _on_task_progress(self, idx, val):
        row_idx = idx
        pbar = self.tableFiles.cellWidget(row_idx, 3)
        if pbar:
            pbar.setValue(int(val * 100))

    def _on_task_finished(self, idx, success, out_path, msg):
        item_status = self.tableFiles.item(idx, 4)
        if item_status:
            if success:
                if out_path == "SKIP":
                    item_status.setText("⏭️ 已跳过")
                    self.stats["skip"] += 1
                    # 跳过时进度条满格
                    pbar = self.tableFiles.cellWidget(idx, 3)
                    if pbar: pbar.setValue(100)
                else:
                    item_status.setText("✅ 已完成")
                    self.stats["done"] += 1
            else:
                item_status.setText("❌ 失败")
                item_status.setToolTip(msg)
                self.stats["fail"] += 1
                logger.error(f"Task {idx} ({self.tableFiles.item(idx, 0).text() if self.tableFiles.item(idx, 0) else 'Unknown'}) failed: {msg}")

        self._update_stats()

    def _on_all_finished(self):
        self.statsFrame.show() # 处理彻底完成后显示统计面板
        self.btnStartProcess.setEnabled(True)
        self.btnSelectFolder.setEnabled(True)
        self.btnReset.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.statusbar.showMessage("任务全部完成")

    def _show_update(self):
        logger.info("执行检查更新")

        data = Tools.get_version()
        current_ver = Tools.get_current_version()

        if data and version.parse(current_ver) < version.parse(data.get("version")):
            logger.info("执行更新...")
            update_window = UpdateDlg(data, parent=self)
            update_window.setModal(True)
            update_window.exec_()
        else:
            logger.info("当前已是最新版本！")
            QMessageBox.information(self, "提示", "当前已是最新版本！")
            return

    def _show_help(self):
        dlg = HelpDialog(self)
        dlg.exec()

    def _show_about(self):
        about_text = """
<div style="text-align: center;">
    <h2 style="color: #0078d4;">多媒体水印助手 v{APP_VER} Pro</h2>
    <p>一款专业级、高性能的批量视频/图片水印工具</p>
</div>
<hr>
<p><b>主要功能：</b></p>
<ul>
  <li>🎬 视频 & 🖼️ 图片全能处理</li>
  <li>🎨 AI 采样智能调色 (Magic Color)</li>
  <li>🌈 动态文字变色与平滑过渡</li>
  <li>⚡ 多任务并发与 GPU 加速</li>
  <li>💾 模板记忆与同步系统</li>
  <li>🔒 安全原地替换原文件</li>
  <li>🎬 场景分隔视频</li>
  <li>🎬 视频合并</li>
  <li>🎬 增加居中水印支持，智能规避算法</li>
  <li>🎬 增加图片分割，智能检测分割线</li>
</ul>

<p>© 2026 SMILEY. 采用 PySide6 与 FFmpeg 强力驱动。</p>
        """
        QMessageBox.about(self, "关于软件", about_text.replace("{APP_VER}", APP_VER))
