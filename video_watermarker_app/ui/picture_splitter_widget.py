#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
图片分割功能面板 Widget。
参照 video_splitter_widget.py 的模块化设计，提供：
  - 文件列表管理（添加/拖拽/清空）
  - 分割参数配置（行列数、边距、分割线处理）
  - 批量分割处理（后台线程）
  - 预览图展示
"""

import os
import sys
import subprocess

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QLineEdit, QGroupBox, QAbstractItemView,
    QCheckBox, QGridLayout, QSpinBox, QComboBox, QSplitter
)

from video_watermarker_app.core.picture_splitter_worker import PictureSplitterWorker
from video_watermarker_app.utils.logger import logger


# 支持的图片格式
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}


def _is_supported_image(path):
    """检查文件是否为支持的图片格式"""
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


class PictureSplitterWidget(QWidget):
    """图片分割功能面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = []
        self.worker = None
        self.qthread = None
        self._current_preview_path = None
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.setAcceptDrops(True)

        # ═══ 顶部操作栏 ═══
        top_layout = QHBoxLayout()
        self.btnAddFiles = QPushButton("🖼️ 添加图片")
        self.btnAddFiles.clicked.connect(self.add_files)
        top_layout.addWidget(self.btnAddFiles)

        self.btnAddFolder = QPushButton("📁 添加文件夹")
        self.btnAddFolder.clicked.connect(self.add_folder)
        top_layout.addWidget(self.btnAddFolder)

        self.btnClear = QPushButton("🗑️ 清空列表")
        self.btnClear.clicked.connect(self.clear_list)
        top_layout.addWidget(self.btnClear)

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # ═══ 中间区域：文件列表 + 预览 ═══
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：文件列表
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["文件名", "大小", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self.table)
        splitter.addWidget(list_widget)

        # 右侧：预览区
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.lblPreviewTitle = QLabel("📋 分割预览")
        self.lblPreviewTitle.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        preview_layout.addWidget(self.lblPreviewTitle)

        self.lblPreview = QLabel("选择已处理的图片查看分割预览")
        self.lblPreview.setAlignment(Qt.AlignCenter)
        self.lblPreview.setMinimumSize(300, 250)
        self.lblPreview.setStyleSheet(
            "background-color: #1a1a1a; border-radius: 8px; color: #888; padding: 10px;"
        )
        preview_layout.addWidget(self.lblPreview)

        self.lblPreviewInfo = QLabel("")
        self.lblPreviewInfo.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        self.lblPreviewInfo.setWordWrap(True)
        preview_layout.addWidget(self.lblPreviewInfo)

        splitter.addWidget(preview_widget)
        splitter.setStretchFactor(0, 3)  # 文件列表占更大比例
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)  # stretch=1 让中间区域占主体

        # ═══ 分割参数设置 ═══
        settings_group = QGroupBox("分割参数")
        settings_layout = QVBoxLayout()

        # 第一行：行列数 + 边距
        params_layout = QHBoxLayout()

        params_layout.addWidget(QLabel("行数:"))
        self.spinRows = QSpinBox()
        self.spinRows.setStyleSheet("")
        self.spinRows.setRange(1, 10)
        self.spinRows.setValue(3)
        self.spinRows.setFixedWidth(100)
        self.spinRows.setToolTip("分割行数，默认 3")
        params_layout.addWidget(self.spinRows)

        params_layout.addWidget(QLabel("列数:"))
        self.spinCols = QSpinBox()
        self.spinCols.setRange(1, 10)
        self.spinCols.setValue(3)
        self.spinCols.setFixedWidth(100)
        self.spinCols.setToolTip("分割列数，默认 3")
        params_layout.addWidget(self.spinCols)

        params_layout.addWidget(QLabel("边距裁切:"))
        self.spinBorder = QSpinBox()
        self.spinBorder.setRange(0, 50)
        self.spinBorder.setValue(2)
        self.spinBorder.setFixedWidth(100)
        self.spinBorder.setSuffix(" px")
        self.spinBorder.setToolTip("裁切后每边再向内缩 N 像素，去除残留线条")
        params_layout.addWidget(self.spinBorder)

        self.chkSkipLine = QCheckBox("智能分割线处理")
        self.chkSkipLine.setChecked(True)
        self.chkSkipLine.setToolTip("自动检测分割线宽度，将线像素各半分给相邻两图")
        params_layout.addWidget(self.chkSkipLine)

        params_layout.addStretch()
        settings_layout.addLayout(params_layout)

        # 第二行：输出目录
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("输出目录:"))
        self.edtOutputDir = QLineEdit()
        self.edtOutputDir.setPlaceholderText("选择保存分割结果的目录 (每张图片将在此目录下以图片名新建子文件夹)...")
        self.edtOutputDir.setReadOnly(True)
        path_layout.addWidget(self.edtOutputDir)
        self.btnSelectOutput = QPushButton("选择...")
        self.btnSelectOutput.clicked.connect(self.select_output_dir)
        path_layout.addWidget(self.btnSelectOutput)
        self.btnOpenOutput = QPushButton("📂 打开")
        self.btnOpenOutput.setToolTip("在文件管理器中打开输出目录")
        self.btnOpenOutput.clicked.connect(self.open_output_dir)
        path_layout.addWidget(self.btnOpenOutput)
        settings_layout.addLayout(path_layout)

        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # ═══ 底部控制区 ═══
        ctrl_layout = QHBoxLayout()

        self.statusLabel = QLabel("准备就绪")
        ctrl_layout.addWidget(self.statusLabel)

        self.pbar = QProgressBar()
        ctrl_layout.addWidget(self.pbar)

        self.btnStart = QPushButton("▶ 开始分割")
        self.btnStart.clicked.connect(self.start_processing)
        self.btnStart.setMinimumHeight(35)
        ctrl_layout.addWidget(self.btnStart)

        self.btnStop = QPushButton("⏹ 停止")
        self.btnStop.clicked.connect(self.stop_processing)
        self.btnStop.setEnabled(False)
        self.btnStop.setMinimumHeight(35)
        ctrl_layout.addWidget(self.btnStop)

        main_layout.addLayout(ctrl_layout)

    # ═══════════════════════════════════════════════════
    #  拖拽支持
    # ═══════════════════════════════════════════════════

    def dragEnterEvent(self, event):
        """拖拽进入事件：接受包含文件 URL 的拖拽"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """拖拽释放事件：提取图片文件并添加到列表"""
        urls = event.mimeData().urls()
        files = []
        first_parent_dir = None
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                if first_parent_dir is None:
                    first_parent_dir = path
                # 递归扫描文件夹中的图片文件
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        if _is_supported_image(fp):
                            files.append(fp)
            elif _is_supported_image(path):
                if first_parent_dir is None:
                    first_parent_dir = os.path.dirname(path)
                files.append(path)

        if files:
            self._append_files(files)
            # 如果输出目录未设置，自动使用拖拽文件的父级目录
            if not self.edtOutputDir.text().strip() and first_parent_dir:
                self.edtOutputDir.setText(first_parent_dir)
            self.statusLabel.setText(f"已通过拖拽添加 {len(files)} 张图片")

    # ═══════════════════════════════════════════════════
    #  文件管理
    # ═══════════════════════════════════════════════════

    def add_files(self):
        """手动选择图片文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片文件", "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif);;All Files (*)"
        )
        if files:
            self._append_files(files)

    def add_folder(self):
        """扫描选择的文件夹"""
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d:
            files = []
            for root, _, fs in os.walk(d):
                for f in fs:
                    fp = os.path.join(root, f)
                    if _is_supported_image(fp):
                        files.append(fp)
            if files:
                self._append_files(files)
                # 自动填充输出目录
                if not self.edtOutputDir.text().strip():
                    self.edtOutputDir.setText(d)

    def _append_files(self, file_paths):
        """将文件添加到列表（去重）"""
        for f in file_paths:
            if f not in self.files:
                self.files.append(f)
                row = self.table.rowCount()
                self.table.insertRow(row)

                name_item = QTableWidgetItem(os.path.basename(f))
                name_item.setToolTip(f)
                name_item.setData(Qt.UserRole, f)  # 存储完整路径
                self.table.setItem(row, 0, name_item)

                try:
                    size_mb = os.path.getsize(f) / (1024 * 1024)
                    self.table.setItem(row, 1, QTableWidgetItem(f"{size_mb:.2f} MB"))
                except:
                    self.table.setItem(row, 1, QTableWidgetItem("N/A"))

                self.table.setItem(row, 2, QTableWidgetItem("等待中"))

    def clear_list(self):
        """清空文件列表"""
        if self.worker is not None:
            QMessageBox.warning(self, "提示", "请先停止当前任务")
            return
        self.files = []
        self.table.setRowCount(0)
        self._clear_preview()

    def _clear_preview(self):
        """清除预览区域"""
        self.lblPreview.setPixmap(QPixmap())
        self.lblPreview.setText("选择已处理的图片查看分割预览")
        self.lblPreviewInfo.setText("")
        self._current_preview_path = None

    # ═══════════════════════════════════════════════════
    #  预览相关
    # ═══════════════════════════════════════════════════

    def _on_selection_changed(self):
        """当用户在列表中选择已完成的项时，显示预览图"""
        items = self.table.selectedItems()
        if not items:
            return

        row = items[0].row()
        status_item = self.table.item(row, 2)
        if not status_item or "完成" not in status_item.text():
            return

        # 根据输出目录和文件名推算预览图路径
        name_item = self.table.item(row, 0)
        if not name_item:
            return

        file_path = name_item.data(Qt.UserRole)
        img_name = os.path.splitext(os.path.basename(file_path))[0]
        output_dir = self.edtOutputDir.text().strip()
        preview_path = os.path.join(output_dir, img_name, "preview_grid.png")

        if os.path.exists(preview_path):
            self._show_preview(preview_path)

    def _show_preview(self, preview_path, info=None):
        """在预览区显示分割预览图"""
        self._current_preview_path = preview_path
        pixmap = QPixmap(preview_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.lblPreview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.lblPreview.setPixmap(scaled)
            self.lblPreview.setText("")

        if info:
            info_text = (
                f"尺寸: {info.get('image_size', 'N/A')}  |  "
                f"类型: {info.get('img_type', 'N/A')}  |  "
                f"行方法: {info.get('row_method', 'N/A')} (conf={info.get('row_conf', 0):.2f})  |  "
                f"列方法: {info.get('col_method', 'N/A')} (conf={info.get('col_conf', 0):.2f})"
            )
            self.lblPreviewInfo.setText(info_text)

    # ═══════════════════════════════════════════════════
    #  输出目录
    # ═══════════════════════════════════════════════════

    def select_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.edtOutputDir.setText(d)

    def open_output_dir(self):
        """在文件管理器中打开输出目录"""
        d = self.edtOutputDir.text().strip()
        if not d or not os.path.isdir(d):
            QMessageBox.warning(self, "提示", "输出目录不存在或未设置")
            return
        if sys.platform == 'win32':
            os.startfile(d)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', d])
        else:
            subprocess.Popen(['xdg-open', d])

    # ═══════════════════════════════════════════════════
    #  处理控制
    # ═══════════════════════════════════════════════════

    def start_processing(self):
        """开始批量图片分割"""
        if not self.files:
            QMessageBox.warning(self, "提示", "请先添加图片文件")
            return

        output_dir = self.edtOutputDir.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "提示", "请选择输出目录")
            return

        rows = self.spinRows.value()
        cols = self.spinCols.value()
        strip_border = self.spinBorder.value()
        skip_split_line = self.chkSkipLine.isChecked()

        # 锁定 UI
        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.table.setEnabled(False)
        self.pbar.setValue(0)

        # 重置所有状态
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 2, QTableWidgetItem("等待中"))

        # 创建后台线程
        self.qthread = QThread()
        self.worker = PictureSplitterWorker(
            file_paths=list(self.files),
            output_dir=output_dir,
            rows=rows,
            cols=cols,
            strip_border=strip_border,
            skip_split_line=skip_split_line
        )
        self.worker.moveToThread(self.qthread)

        # 连接信号
        self.qthread.started.connect(self.worker.run)
        self.worker.finished.connect(self.qthread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.qthread.finished.connect(self.qthread.deleteLater)
        self.qthread.finished.connect(self._on_finished)

        self.worker.progress.connect(self._on_progress)
        self.worker.file_status.connect(self._on_file_status)
        self.worker.file_result.connect(self._on_file_result)
        self.worker.error.connect(self._on_error)

        self.qthread.start()

    def stop_processing(self):
        """停止处理"""
        if self.worker:
            self.worker.stop()
        self.btnStop.setEnabled(False)
        self.statusLabel.setText("正在停止...")

    def _on_progress(self, val, msg):
        self.pbar.setValue(val)
        self.statusLabel.setText(msg)

    def _on_file_status(self, idx, status_text):
        """更新表格中对应行的状态列"""
        if 0 <= idx < self.table.rowCount():
            self.table.setItem(idx, 2, QTableWidgetItem(status_text))

    def _on_file_result(self, idx, saved_paths, preview_path, info):
        """处理单张图片完成后的回调：显示最新预览"""
        if preview_path and os.path.exists(preview_path):
            self._show_preview(preview_path, info)

    def _on_error(self, msg):
        logger.error(msg)
        QMessageBox.warning(self, "错误", msg)

    def _on_finished(self):
        """所有任务完成"""
        self.worker = None
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.table.setEnabled(True)
        self.pbar.setValue(100)
        self.statusLabel.setText("任务完成")
        QMessageBox.information(self, "完成", "所有图片分割任务已完成！")

    # ═══════════════════════════════════════════════════
    #  键盘事件
    # ═══════════════════════════════════════════════════

    def keyPressEvent(self, event):
        """Delete 键删除选中项"""
        if event.key() == Qt.Key_Delete:
            selected_rows = sorted(
                set(index.row() for index in self.table.selectedIndexes()),
                reverse=True
            )
            for row in selected_rows:
                file_path = self.table.item(row, 0).data(Qt.UserRole)
                if file_path in self.files:
                    self.files.remove(file_path)
                self.table.removeRow(row)
        else:
            super().keyPressEvent(event)
