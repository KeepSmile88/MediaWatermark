#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import copy
import time
import tempfile
import subprocess

from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QLineEdit, QGroupBox, QAbstractItemView,
    QCheckBox, QGridLayout
)
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from video_watermarker_app.utils.logger import logger
from video_watermarker_app.utils.common import (
    check_ffmpeg, default_font_path, find_font_path,
    to_ffmpeg_filter_path, is_image_file, is_video_file,
    get_available_encoders, get_gpu_params
)
from video_watermarker_app.utils.config import WatermarkConfig


class VideoSplitterWorker(QObject):
    """视频分割后台工作线程"""
    finished = Signal()
    progress = Signal(int, str)  # 百分比, 消息
    file_status = Signal(int, str)  # 文件索引, 状态文本
    error = Signal(str)

    def __init__(self, file_paths, output_dir, threshold=27.0,
                 wm_config=None, add_watermark=False, use_timestamp=False):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.threshold = threshold
        self.wm_config = wm_config  # 共享的 WatermarkConfig 对象
        self.add_watermark = add_watermark
        self.use_timestamp = use_timestamp
        self._is_running = True

    def _build_multi_wm_filter(self, main_w, main_h, video_path=None):
        """
        构建多水印链式滤镜图（主水印 + 额外水印层）。
        返回: (vf_string, txt_temp_files, image_input_paths, uses_filter_complex)
        """
        cfg = self.wm_config
        if not cfg:
            return None, [], [], False

        # 收集所有水印配置
        all_cfgs = [cfg]
        if hasattr(cfg, 'extra_watermarks') and cfg.extra_watermarks:
            for extra in cfg.extra_watermarks:
                if isinstance(extra, WatermarkConfig):
                    all_cfgs.append(extra)

        filter_parts = []
        txt_files = []
        image_inputs = []
        input_idx = 1  # 0 是主视频
        current_label = "[0:v]"
        has_image = False

        for i, wm_cfg in enumerate(all_cfgs):
            is_last = (i == len(all_cfgs) - 1)
            out_label = "[v]" if is_last else f"[v{i}]"

            if wm_cfg.wm_type == "image":
                if not wm_cfg.image_path or not os.path.exists(wm_cfg.image_path):
                    if is_last and filter_parts:
                        filter_parts[-1] = filter_parts[-1].rsplit("[", 1)[0] + "[v]"
                    continue

                has_image = True
                image_inputs.append(wm_cfg.image_path)
                img_stream = f"[{input_idx}:v]"
                input_idx += 1

                margin = wm_cfg.margin
                wm_w = max(1, int(main_w * (wm_cfg.image_scale_pct / 100.0)))

                pos_map = {
                    "左上": (f"{margin}", f"{margin}"),
                    "右上": (f"main_w-overlay_w-{margin}", f"{margin}"),
                    "左下": (f"{margin}", f"main_h-overlay_h-{margin}"),
                    "右下": (f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"),
                    "居中": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
                }
                x, y = pos_map.get(wm_cfg.position, (str(wm_cfg.custom_x), str(wm_cfg.custom_y)))

                feather = ""
                if wm_cfg.feather_radius > 0:
                    rad = wm_cfg.feather_radius
                    feather = f",boxblur={rad}:1:{rad}:1:{rad}:1"

                wm_label = f"[wm{i}]"
                part = (
                    f"{img_stream}format=rgba,scale={wm_w}:-1,"
                    f"colorchannelmixer=aa={wm_cfg.opacity:.2f}{feather}{wm_label};"
                    f"{current_label}{wm_label}overlay=x={x}:y={y}:shortest=1{out_label}"
                )
                filter_parts.append(part)
                current_label = out_label

            elif wm_cfg.wm_type == "text":
                if not wm_cfg.text:
                    if is_last and filter_parts:
                        filter_parts[-1] = filter_parts[-1].rsplit("[", 1)[0] + "[v]"
                    continue

                try:
                    fd, txt_path = tempfile.mkstemp(suffix=".txt")
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(wm_cfg.text)
                    txt_files.append(txt_path)
                except Exception as e:
                    logger.error(f"创建临时文本文件失败: {e}")
                    continue

                margin = wm_cfg.margin
                alpha = wm_cfg.opacity
                fs = max(1, int(main_h * (wm_cfg.text_size_pct / 100.0)))
                fontfile = find_font_path(wm_cfg.font_name)

                pos_map = {
                    "左上": (f"{margin}", f"{margin}"),
                    "右上": (f"w-text_w-{margin}", f"{margin}"),
                    "左下": (f"{margin}", f"h-text_h-{margin}"),
                    "右下": (f"w-text_w-{margin}", f"h-text_h-{margin}"),
                    "居中": ("(w-text_w)/2", "(h-text_h)/2"),
                }
                x_expr, y_expr = pos_map.get(wm_cfg.position, (str(wm_cfg.custom_x), str(wm_cfg.custom_y)))

                font_color = wm_cfg.font_color or "#FFFFFF"
                border_color = wm_cfg.border_color or "#000000"
                border_w = 2  # 默认描边

                # 构建 drawtext 参数
                parts = []
                if fontfile and os.path.exists(fontfile):
                    parts.append(f"fontfile='{to_ffmpeg_filter_path(fontfile)}'")
                parts.append(f"textfile='{to_ffmpeg_filter_path(txt_path)}'")
                parts.append(f"fontsize={fs}")

                hex_color = font_color.replace("#", "0x")
                parts.append(f"fontcolor={hex_color}@{alpha:.2f}")
                parts.append(f"borderw={border_w}")
                parts.append(f"bordercolor={border_color.replace('#', '0x')}")
                parts.append(f"x={x_expr}")
                parts.append(f"y={y_expr}")

                part = f"{current_label}drawtext={':'.join(parts)}{out_label}"
                filter_parts.append(part)
                current_label = out_label

        if not filter_parts:
            return None, txt_files, image_inputs, False

        vf = ";".join(filter_parts)
        uses_complex = has_image or len(all_cfgs) > 1
        return vf, txt_files, image_inputs, uses_complex

    def run(self):
        total_files = len(self.file_paths)
        ffmpeg_exe, ffprobe_exe = check_ffmpeg()
        if not ffmpeg_exe:
            self.error.emit("未找到 FFmpeg，请检查安装。")
            self.finished.emit()
            return

        for i, video_path in enumerate(self.file_paths):
            if not self._is_running:
                break

            txt_temp_files = []
            try:
                video_name = os.path.splitext(os.path.basename(video_path))[0]
                self.file_status.emit(i, "🔍 分析中...")
                self.progress.emit(int((i / total_files) * 100), f"正在分析场景: {video_name}...")

                output_folder = os.path.join(self.output_dir, video_name)
                os.makedirs(output_folder, exist_ok=True)

                # 场景检测
                video = open_video(video_path)
                scene_manager = SceneManager()
                scene_manager.add_detector(ContentDetector(threshold=self.threshold))

                scene_manager.detect_scenes(video, show_progress=False)
                scene_list = scene_manager.get_scene_list()

                if not scene_list:
                    from scenedetect import FrameTimecode
                    start = FrameTimecode(timecode=0, fps=video.frame_rate)
                    end = FrameTimecode(timecode=video.duration.frame_num, fps=video.frame_rate)
                    scene_list = [(start, end)]
                    logger.warning(f"{video_name} 未检测到场景变化，将作为一个片段处理。")
                    self.file_status.emit(i, "⚠️ 无场景变化")

                total_scenes = len(scene_list)
                logger.info(f"{video_name} 检测到 {total_scenes} 个场景")

                # 获取视频分辨率
                main_w, main_h = 1920, 1080
                if ffprobe_exe and self.add_watermark:
                    try:
                        probe_cmd = [
                            ffprobe_exe, '-v', 'error',
                            '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height',
                            '-of', 'csv=s=x:p=0', video_path
                        ]
                        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        res = subprocess.run(probe_cmd, capture_output=True, text=True,
                                             timeout=10, creationflags=creation_flags)
                        if res.returncode == 0 and 'x' in res.stdout.strip():
                            parts = res.stdout.strip().split('x')
                            main_w, main_h = int(parts[0]), int(parts[1])
                    except Exception as e:
                        logger.warning(f"获取视频分辨率失败: {e}")

                # 预构建多水印滤镜
                vf_string = None
                image_inputs = []
                uses_complex = False
                if self.add_watermark and self.wm_config:
                    vf_string, txt_temp_files, image_inputs, uses_complex = self._build_multi_wm_filter(
                        main_w, main_h, video_path
                    )

                for j, scene in enumerate(scene_list):
                    if not self._is_running:
                        break

                    start_sec = scene[0].get_seconds()
                    end_sec = scene[1].get_seconds()
                    duration = end_sec - start_sec

                    if duration < 0.5:
                        continue

                    if self.use_timestamp:
                        clip_name = f"clip_{j + 1:03d}_{int(time.time() * 1000)}.mp4"
                    else:
                        clip_name = f"clip_{j + 1:03d}.mp4"
                    output_file = os.path.join(output_folder, clip_name)

                    msg = f"正在处理: {video_name} ({j + 1}/{total_scenes})"
                    overall_pct = int(((i + (j / total_scenes)) / total_files) * 100)
                    self.progress.emit(overall_pct, msg)
                    self.file_status.emit(i, f"✂️ 切割中 ({j + 1}/{total_scenes})")

                    # 构建 ffmpeg 命令
                    cmd = [ffmpeg_exe, '-y']

                    # GPU 硬件加速
                    use_gpu = self.wm_config.gpu_enabled if self.wm_config else False
                    if use_gpu:
                        cmd.extend(['-hwaccel', 'cuda'])

                    # 主输入
                    cmd.extend(['-i', video_path])

                    # 图片水印额外输入
                    for img_path in image_inputs:
                        cmd.extend(['-i', str(img_path)])

                    # 时间切割
                    cmd.extend(['-ss', f"{start_sec:.3f}", '-to', f"{end_sec:.3f}"])

                    # 滤镜
                    if vf_string:
                        if uses_complex:
                            cmd.extend(['-filter_complex', vf_string, '-map', '[v]', '-map', '0:a?'])
                        else:
                            # 单文字水印可以用简单 -vf（去掉 [0:v] 和 [v] 标签）
                            simple_vf = vf_string.replace("[0:v]", "").replace("[v]", "")
                            cmd.extend(['-vf', simple_vf])

                    # 编码器设置
                    if use_gpu:
                        cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
                    else:
                        crf = self.wm_config.crf if self.wm_config else 23
                        preset = self.wm_config.preset if self.wm_config else 'medium'
                        cmd.extend(['-c:v', 'libx264', '-crf', str(crf), '-preset', preset])

                    cmd.extend(['-c:a', 'copy'])
                    cmd.append(output_file)

                    # 执行
                    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    subprocess.run(cmd, creationflags=creation_flags, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # 当前视频所有场景处理完成
                self.file_status.emit(i, f"✅ 完成 ({total_scenes}个片段)")

            except Exception as e:
                logger.error(f"处理视频 {video_path} 失败: {e}", exc_info=True)
                self.error.emit(f"处理 {os.path.basename(video_path)} 时出错: {str(e)}")
                self.file_status.emit(i, "❌ 失败")
            finally:
                # 清理临时文件
                for tf in txt_temp_files:
                    if tf and os.path.exists(tf):
                        try:
                            os.unlink(tf)
                        except:
                            pass

        self.progress.emit(100, "处理完成")
        self.finished.emit()

    def stop(self):
        self._is_running = False


class VideoSplitterWidget(QWidget):
    """视频分割功能面板，水印设置与主窗口水印功能共享"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = []
        self.worker = None
        self.qthread = None
        self._wm_config = None  # 由外部 (MainWindow) 注入
        self.setup_ui()

    def set_watermark_config(self, cfg: WatermarkConfig):
        """由 MainWindow 调用，传入共享的水印配置"""
        self._wm_config = cfg
        # 更新 UI 上的水印状态提示
        self._update_wm_status_label()

    def _update_wm_status_label(self):
        """更新水印状态标签，显示所有水印层信息"""
        if not self._wm_config:
            self.lblWmStatus.setText("⚠️ 水印配置未加载")
            return
        cfg = self._wm_config

        # 构建主水印描述
        lines = []
        if cfg.wm_type == "image":
            name = os.path.basename(cfg.image_path) if cfg.image_path else "未设置"
            lines.append(f"🖼️ 主水印(图片): {name} | 位置: {cfg.position}")
        elif cfg.wm_type == "text":
            lines.append(f"📝 主水印(文字): \"{cfg.text}\" | 位置: {cfg.position}")
        else:
            lines.append("无水印")

        # 额外水印层
        extras = getattr(cfg, 'extra_watermarks', None) or []
        for idx, ex in enumerate(extras, start=1):
            if ex.wm_type == "image":
                name = os.path.basename(ex.image_path) if ex.image_path else "未设置"
                lines.append(f"🖼️ 额外层{idx}(图片): {name} | 位置: {ex.position}")
            elif ex.wm_type == "text":
                lines.append(f"📝 额外层{idx}(文字): \"{ex.text}\" | 位置: {ex.position}")

        self.lblWmStatus.setText("\n".join(lines))

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setAcceptDrops(True)

        top_layout = QHBoxLayout()
        self.btnAddFiles = QPushButton("📽️ 添加视频")
        self.btnAddFiles.clicked.connect(self.add_files)
        top_layout.addWidget(self.btnAddFiles)

        self.btnAddFolder = QPushButton("📁 添加文件夹")
        self.btnAddFolder.clicked.connect(self.add_folder)
        top_layout.addWidget(self.btnAddFolder)

        self.btnClear = QPushButton("🗑️ 清空列表")
        self.btnClear.clicked.connect(self.clear_list)
        top_layout.addWidget(self.btnClear)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        # --- 文件列表 ---
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
        layout.addWidget(self.table)

        # --- 输出与处理设置 ---
        settings_group = QGroupBox("输出与处理设置")
        settings_layout = QVBoxLayout()

        # 目录选择
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("输出目录:"))
        self.edtOutputDir = QLineEdit()
        self.edtOutputDir.setPlaceholderText("选择保存分割视频的根目录 (每个视频将在此目录下以视频名新建子文件夹)...")
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

        # 阈值
        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("场景切割阈值:"))
        self.edtThreshold = QLineEdit("27.0")
        self.edtThreshold.setFixedWidth(60)
        self.edtThreshold.setToolTip("值越小越敏感，检测出越多场景。默认 27.0")
        options_layout.addWidget(self.edtThreshold)

        self.chkUseTimestamp = QCheckBox("文件名使用时间戳")
        self.chkUseTimestamp.setToolTip("勾选后，导出的碎片文件名将使用当前系统时间戳，例如: 1680000000000.mp4")
        options_layout.addWidget(self.chkUseTimestamp)

        options_layout.addStretch()
        settings_layout.addLayout(options_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # --- 水印设置（共享） ---
        wm_group = QGroupBox("水印设置")
        wm_layout = QVBoxLayout()

        self.chkAddWatermark = QCheckBox("切割时同时添加水印")
        self.chkAddWatermark.setToolTip("启用后，将使用「视频水印」标签页中配置的水印设置")
        wm_layout.addWidget(self.chkAddWatermark)

        self.lblWmStatus = QLabel("⚠️ 水印配置未加载")
        self.lblWmStatus.setStyleSheet("color: #888; padding-left: 20px;")
        wm_layout.addWidget(self.lblWmStatus)

        hint_label = QLabel("💡 提示：水印参数在「视频水印」标签页的设置中统一管理。")
        hint_label.setStyleSheet("color: #666; font-size: 11px; padding-left: 20px;")
        wm_layout.addWidget(hint_label)

        wm_group.setLayout(wm_layout)
        layout.addWidget(wm_group)

        # --- 控制区 ---
        ctrl_layout = QHBoxLayout()
        self.statusLabel = QLabel("准备就绪")
        ctrl_layout.addWidget(self.statusLabel)

        self.pbar = QProgressBar()
        ctrl_layout.addWidget(self.pbar)

        self.btnStart = QPushButton("▶ 开始处理")
        self.btnStart.clicked.connect(self.start_processing)
        self.btnStart.setMinimumHeight(35)
        ctrl_layout.addWidget(self.btnStart)

        self.btnStop = QPushButton("⏹ 停止")
        self.btnStop.clicked.connect(self.stop_processing)
        self.btnStop.setEnabled(False)
        self.btnStop.setMinimumHeight(35)
        ctrl_layout.addWidget(self.btnStop)

        layout.addLayout(ctrl_layout)

    # --- 拖拽支持 ---
    def dragEnterEvent(self, event):
        """拖拽进入事件：接受包含文件 URL 的拖拽"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """拖拽释放事件：提取视频文件并添加到列表"""
        urls = event.mimeData().urls()
        files = []
        first_parent_dir = None
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                if first_parent_dir is None:
                    first_parent_dir = path  # 文件夹本身作为默认输出目录
                # 递归扫描文件夹中的视频文件
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        if is_video_file(fp):
                            files.append(fp)
            elif is_video_file(path):
                if first_parent_dir is None:
                    first_parent_dir = os.path.dirname(path)
                files.append(path)

        if files:
            self._append_files(files)
            # 如果输出目录未设置，自动使用拖拽文件的父级目录
            if not self.edtOutputDir.text().strip() and first_parent_dir:
                self.edtOutputDir.setText(first_parent_dir)
            self.statusLabel.setText(f"已通过拖拽添加 {len(files)} 个视频文件")

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", "",
            "Video Files (*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm *.ts);;All Files (*)"
        )
        if files:
            self._append_files(files)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d:
            files = []
            for root, _, fs in os.walk(d):
                for f in fs:
                    if f.lower().endswith(('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv', '.webm', '.ts')):
                        files.append(os.path.join(root, f))
            self._append_files(files)

    def _append_files(self, file_paths):
        for f in file_paths:
            if f not in self.files:
                self.files.append(f)
                row = self.table.rowCount()
                self.table.insertRow(row)

                name_item = QTableWidgetItem(os.path.basename(f))
                name_item.setToolTip(f)
                self.table.setItem(row, 0, name_item)

                try:
                    size_mb = os.path.getsize(f) / (1024 * 1024)
                    self.table.setItem(row, 1, QTableWidgetItem(f"{size_mb:.2f} MB"))
                except:
                    self.table.setItem(row, 1, QTableWidgetItem("N/A"))

                self.table.setItem(row, 2, QTableWidgetItem("等待中"))

    def clear_list(self):
        if self.worker is not None:
            QMessageBox.warning(self, "提示", "请先停止当前任务")
            return
        self.files = []
        self.table.setRowCount(0)

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

    def start_processing(self):
        if not self.files:
            QMessageBox.warning(self, "提示", "请先添加视频文件")
            return

        output_dir = self.edtOutputDir.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "提示", "请选择输出目录")
            return

        try:
            threshold = float(self.edtThreshold.text().strip())
        except ValueError:
            QMessageBox.warning(self, "提示", "请输入有效的阈值数字")
            return

        add_watermark = self.chkAddWatermark.isChecked()
        if add_watermark and not self._wm_config:
            QMessageBox.warning(self, "提示", "水印配置未加载，请先在「视频水印」标签页中配置水印设置")
            return

        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.table.setEnabled(False)
        self.pbar.setValue(0)

        for row in range(self.table.rowCount()):
            self.table.setItem(row, 2, QTableWidgetItem("等待中"))

        # 深拷贝配置，防止处理过程中被主界面修改
        wm_cfg_copy = copy.deepcopy(self._wm_config) if self._wm_config else None

        self.qthread = QThread()
        self.worker = VideoSplitterWorker(
            file_paths=list(self.files),
            output_dir=output_dir,
            threshold=threshold,
            wm_config=wm_cfg_copy,
            add_watermark=add_watermark,
            use_timestamp=self.chkUseTimestamp.isChecked()
        )
        self.worker.moveToThread(self.qthread)

        self.qthread.started.connect(self.worker.run)
        self.worker.finished.connect(self.qthread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.qthread.finished.connect(self.qthread.deleteLater)
        self.qthread.finished.connect(self._on_finished)

        self.worker.progress.connect(self._on_progress)
        self.worker.file_status.connect(self._on_file_status)
        self.worker.error.connect(self._on_error)

        self.qthread.start()

    def stop_processing(self):
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

    def _on_error(self, msg):
        logger.error(msg)
        QMessageBox.warning(self, "错误", msg)

    def _on_finished(self):
        self.worker = None
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.table.setEnabled(True)
        self.pbar.setValue(100)
        self.statusLabel.setText("任务完成")
        QMessageBox.information(self, "完成", "所有视频分割任务已完成！")
