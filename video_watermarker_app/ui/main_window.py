#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import copy
import tempfile
import subprocess

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QMovie, QIcon, QAction, QPixmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QMainWindow, QFileDialog, QTableWidgetItem, QHeaderView, QLabel, QMessageBox, QWidget, QProgressBar

from video_watermarker_app.ui.ui_mainwindow import Ui_MainWindow
from video_watermarker_app.ui.settings_dialog import SettingsDialog
from video_watermarker_app.ui.help_dialog import HelpDialog
from video_watermarker_app.core.ffmpeg_worker import WatermarkWorker
from video_watermarker_app.utils.config import AppConfig, WatermarkConfig
from video_watermarker_app.utils.common import is_video_file, is_image_file, check_ffmpeg, to_ffmpeg_filter_path, default_font_path
from video_watermarker_app.utils.logger import logger
from video_watermarker_app.GLOBAL import APP_NAME

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle(APP_NAME)

        self.app_config = AppConfig()
        self.current_cfg = self.app_config.load_last_config()

        self.lblWatermarkPreview.setAlignment(Qt.AlignCenter)
        self.active_workers = {}
        self.task_queue = []
        self.stats = {"total": 0, "done": 0, "fail": 0, "skip": 0}
        self.current_preview_frame = None # QPixmap
        self.current_selected_path = None

        self.btnClearWatermark.clicked.connect(self._clear_watermark)
        self.btnSelectFolder.clicked.connect(self._add_folder)
        self.btnStartProcess.clicked.connect(self._start_task)
        self.btnStop.clicked.connect(self._stop_all_tasks)
        self.btnReset.clicked.connect(self._reset_tasks)
        
        self.actionSettings.triggered.connect(self._open_settings)
        self.actionClearHistory.triggered.connect(self._clear_history)
        self.actionHelp.triggered.connect(self._show_help)
        self.actionAbout.triggered.connect(self._show_about)
        self.actionExit.triggered.connect(self.close)
        self.tableFiles.itemSelectionChanged.connect(self._on_selection_changed)
        self.tableFiles.customContextMenuRequested.connect(self._on_table_context_menu)

        self.setAcceptDrops(True)

        self.lblCurrentFolder.setText("未选择文件夹")

        self._refresh_watermark_view()

    def _refresh_watermark_view(self):
        """刷新左侧面板的水印预览状态"""

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

            safe_h = max(h, 100) 
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
            painter.drawText(x, y + metrics.ascent(), display_text)
            
        painter.end()

        final = canvas.scaled(self.lblWatermarkPreview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lblWatermarkPreview.setPixmap(final)
        self.lblWatermarkPreview.update()

    def _get_overlay_pos(self, position, mw, mh, sw, sh, margin):
        if position == "左上": return (margin, margin)
        if position == "右上": return (mw - sw - margin, margin)
        if position == "左下": return (margin, mh - sh - margin)
        if position == "右下": return (mw - sw - margin, mh - sh - margin)
        if position == "居中": return ((mw - sw) // 2, (mh - sh) // 2)
        if position == "自定义": return (self.current_cfg.custom_x, self.current_cfg.custom_y)
        return (margin, margin)

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

        if is_image_file(path):
            self.current_preview_frame = QPixmap(path)
            self._draw_preview_overlay()
        else:
            self._extract_frame(path)

    def _extract_frame(self, path):
        ffmpeg, _ = check_ffmpeg()
        if not ffmpeg: return

        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        tmp.close()
        
        cmd = [ffmpeg, "-y", "-ss", "00:00:01", "-i", path, "-frames:v", "1", "-q:v", "2", tmp.name]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=5, shell=True)
            self.current_preview_frame = QPixmap(tmp.name)
            self._draw_preview_overlay()
        except:
            self.current_preview_frame = None
            self._refresh_watermark_view()
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.config_changed.connect(self._on_config_changed_live)
        if dlg.exec():
            self.current_cfg = self.app_config.load_last_config()
            self._refresh_watermark_view()
            self.statusbar.showMessage("设置已保存", 3000)

    def _clear_history(self):
        from video_watermarker_app.utils.config import HistoryManager
        msg = "确定要清空所有处理记录吗？\n清空后之前处理过的视频将不再被自动跳过。"
        ret = QMessageBox.question(self, "确认", msg, QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            HistoryManager().clear()
            self.statusbar.showMessage("处理历史记录已清空", 3000)
            self._reset_tasks()

    def _on_config_changed_live(self, cfg):
        self.current_cfg = cfg
        self.statusbar.showMessage(f"预览同步中: {cfg.wm_type} | {cfg.position}", 1000)
        self._refresh_watermark_view()

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
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        if is_video_file(fp) or is_image_file(fp):
                            files.append(fp)
            else:
                if is_left and is_image_file(path):
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
        from PySide6.QtWidgets import QMenu
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

        self._schedule_tasks()

    def _schedule_tasks(self):
        """调度器：根据并发限制启动任务"""
        try:
            max_concurrent = self.current_cfg.max_concurrent

            while len(self.active_workers) < max_concurrent and self.task_queue:
                idx, path = self.task_queue.pop(0)
                
                # 使用深拷贝，防止主界面修改设置时干扰正在进行的任务
                worker_cfg = copy.deepcopy(self.current_cfg)
                
                worker = WatermarkWorker(idx, path, worker_cfg)
                worker.task_started.connect(self._on_task_started)
                worker.task_progress.connect(self._on_task_progress)
                worker.task_finished.connect(self._on_task_finished)
                worker.finished.connect(lambda i=idx: self._on_worker_teardown(i))
                worker.finished.connect(worker.deleteLater)
                
                self.active_workers[idx] = worker
                worker.start()

            if not self.active_workers and not self.task_queue:
                self._on_all_finished()
        except Exception as e:
            logger.error(f"任务调度异常: {e}")
            self.statusbar.showMessage(f"调度出错: {e}")

    def _on_worker_teardown(self, idx):
        """线程彻底结束后的收尾工作"""
        if idx in self.active_workers:
            del self.active_workers[idx]
        self._schedule_tasks()

    def _stop_all_tasks(self):
        """取消所有任务"""
        self.task_queue = []
        for idx, worker in self.active_workers.items():
            worker.stop()
        self.statusbar.showMessage("正在停止所有任务...")
        self.btnStop.setEnabled(False)

    def _on_task_started(self, idx, path):
        item = self.tableFiles.item(idx, 4)
        if item:
            item.setText("正在处理")
        self.statusbar.showMessage(f"已启动任务: {os.path.basename(path)}")

    def _on_task_progress(self, idx, val):
        # 如果 worker 成功发射了正确的 idx (现在我们在构造函数里传了)
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
        self.statsFrame.show()
        self.btnStartProcess.setEnabled(True)
        self.btnSelectFolder.setEnabled(True)
        self.btnReset.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.statusbar.showMessage("任务全部完成")

    def _show_help(self):
        dlg = HelpDialog(self)
        dlg.exec()

    def _show_about(self):
        about_text = """
<div style="text-align: center;">
    <h2 style="color: #0078d4;">多媒体水印助手 v2.1 Pro</h2>
    <p>一款专业级、高性能的批量视频/图片水印工具</p>
</div>
<hr>
<p><b>主要功能：</b></p>
<ul>
  <li>🎬 视频 & 🖼️ 图片全能处理</li>
  <li>🎨 AI 采样智能调色 (Magic Color)</li>
  <li>⚡ 多任务并发与 GPU 加速</li>
  <li>💾 模板记忆与同步系统</li>
  <li>🔒 安全原地替换原文件</li>
</ul>
<p>© 2026 SMILEY. 采用 PySide6 与 FFmpeg 强力驱动。</p>
        """
        QMessageBox.about(self, "关于软件", about_text)
