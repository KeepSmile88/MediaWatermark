# -*- coding: utf-8 -*-
"""
视频合成面板：支持批量拖拽多个视频文件，按基础名自动分组，
同名不同序号的文件合并后原地输出。可选在合成同时添加水印。
"""
import os
import re
import sys
import copy
import subprocess
import tempfile
from collections import defaultdict

from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QGroupBox, QAbstractItemView,
    QCheckBox
)

from video_watermarker_app.utils.logger import logger
from video_watermarker_app.utils.common import (
    check_ffmpeg, is_video_file, find_font_path, to_ffmpeg_filter_path
)
from video_watermarker_app.utils.config import WatermarkConfig


def _extract_base_name(filename: str) -> str:
    """
    从文件名（不含扩展名）中去除尾部数字序号，返回基础名。
    例如：
      'clip_001' -> 'clip_'
      'video2'   -> 'video'
      'my_video' -> 'my_video'（无尾部数字，原样返回）
    """
    stem = os.path.splitext(filename)[0]
    return re.sub(r'\d+$', '', stem)


def _group_files_by_base(file_paths: list) -> dict:
    """
    按基础名 + 所在目录 对文件进行分组。
    返回: { (目录, 基础名): [路径1, 路径2, ...], ... }
    组内文件按文件名排序（确保序号顺序）。
    """
    groups = defaultdict(list)
    for fp in file_paths:
        dirname = os.path.dirname(fp)
        basename = os.path.basename(fp)
        base = _extract_base_name(basename)
        # 使用 (目录, 基础名) 作为分组键，避免不同目录的同名文件混在一起
        key = (dirname, base)
        groups[key].append(fp)

    # 组内按文件名排序
    for key in groups:
        groups[key].sort(key=lambda p: os.path.basename(p).lower())

    return dict(groups)


def _build_merge_tasks(file_paths: list) -> list:
    """
    根据文件列表构建合并任务。
    返回: [ { 'files': [路径...], 'output': 输出路径, 'group_name': 分组名 }, ... ]
    只有包含 2 个及以上文件的分组才会生成合并任务。
    """
    groups = _group_files_by_base(file_paths)
    tasks = []
    for (dirname, base), paths in groups.items():
        if len(paths) < 2:
            # 单个文件无法合并，跳过
            continue
        # 输出文件名：基础名 + merged.mp4
        output_name = f"{base}merged.mp4"
        output_path = os.path.join(dirname, output_name)
        group_name = base.rstrip('_') if base else "unknown"
        tasks.append({
            'files': paths,
            'output': output_path,
            'group_name': group_name,
        })
    return tasks


class VideoMergerWorker(QObject):
    """视频合成后台工作线程，支持批量处理多组合并任务，可选添加水印"""
    finished = Signal()
    progress = Signal(int, str)          # 总进度百分比, 消息
    group_status = Signal(str, str)      # 分组名, 状态文本
    file_status = Signal(str, str)       # 文件路径, 状态文本
    error = Signal(str)

    def __init__(self, merge_tasks: list, wm_config=None, add_watermark=False):
        """
        merge_tasks: [ { 'files': [...], 'output': '...', 'group_name': '...' }, ... ]
        wm_config: 水印配置（WatermarkConfig 对象，已深拷贝）
        add_watermark: 是否在合成时添加水印
        """
        super().__init__()
        self.merge_tasks = merge_tasks
        self.wm_config = wm_config
        self.add_watermark = add_watermark
        self._is_running = True

    def _build_multi_wm_filter(self, main_w, main_h):
        """
        构建多水印链式滤镜图（主水印 + 额外水印层）。
        返回: (vf_string, txt_temp_files, image_input_paths, uses_filter_complex)
        与 VideoSplitterWorker 中的实现保持一致。
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
                border_w = 2

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

    def _get_video_resolution(self, video_path):
        """获取视频分辨率，返回 (宽, 高)"""
        _, ffprobe_exe = check_ffmpeg()
        if not ffprobe_exe:
            return 1920, 1080
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
                return int(parts[0]), int(parts[1])
        except Exception as e:
            logger.warning(f"获取视频分辨率失败: {e}")
        return 1920, 1080

    def run(self):
        """逐组执行 ffmpeg concat 合并（可选添加水印）"""
        ffmpeg_exe, _ = check_ffmpeg()
        if not ffmpeg_exe:
            self.error.emit("未找到 FFmpeg，请检查安装。")
            self.finished.emit()
            return

        total_tasks = len(self.merge_tasks)
        success_count = 0
        fail_count = 0

        for task_idx, task in enumerate(self.merge_tasks):
            if not self._is_running:
                break

            group_name = task['group_name']
            files = task['files']
            output_path = task['output']
            concat_file = None
            txt_temp_files = []

            try:
                pct = int((task_idx / total_tasks) * 100)
                self.progress.emit(pct, f"正在合并分组「{group_name}」({task_idx + 1}/{total_tasks})...")
                self.group_status.emit(group_name, "🔄 合并中...")

                # 更新组内所有文件状态
                for fp in files:
                    self.file_status.emit(fp, "🔄 合并中...")

                # 创建 concat 列表临时文件
                fd, concat_file = tempfile.mkstemp(suffix=".txt")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for vp in files:
                        safe_path = vp.replace("'", "'\\''")
                        f.write(f"file '{safe_path}'\n")

                if not self._is_running:
                    break

                # 构建 ffmpeg 命令
                cmd = [ffmpeg_exe, '-y']

                # 判断是否需要添加水印
                need_watermark = self.add_watermark and self.wm_config
                vf_string = None
                image_inputs = []
                uses_complex = False

                if need_watermark:
                    # 获取第一个视频的分辨率作为参考
                    main_w, main_h = self._get_video_resolution(files[0])

                    # GPU 硬件加速
                    use_gpu = self.wm_config.gpu_enabled if self.wm_config else False
                    if use_gpu:
                        cmd.extend(['-hwaccel', 'cuda'])

                    # 构建水印滤镜
                    vf_string, txt_temp_files, image_inputs, uses_complex = \
                        self._build_multi_wm_filter(main_w, main_h)

                # concat demuxer 输入
                cmd.extend(['-f', 'concat', '-safe', '0', '-i', concat_file])

                # 图片水印额外输入
                for img_path in image_inputs:
                    cmd.extend(['-i', str(img_path)])

                # 滤镜与编码
                if vf_string:
                    if uses_complex:
                        cmd.extend(['-filter_complex', vf_string, '-map', '[v]', '-map', '0:a?'])
                    else:
                        simple_vf = vf_string.replace("[0:v]", "").replace("[v]", "")
                        cmd.extend(['-vf', simple_vf])

                    # 需要重编码
                    use_gpu = self.wm_config.gpu_enabled if self.wm_config else False
                    if use_gpu:
                        cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
                    else:
                        crf = self.wm_config.crf if self.wm_config else 23
                        preset = self.wm_config.preset if self.wm_config else 'medium'
                        cmd.extend(['-c:v', 'libx264', '-crf', str(crf), '-preset', preset])
                    cmd.extend(['-c:a', 'copy'])
                else:
                    # 无水印，直接复制流（无重编码）
                    cmd.extend(['-c', 'copy'])

                cmd.append(output_path)

                logger.info(f"视频合成命令 [{group_name}]: {' '.join(cmd)}")

                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=creation_flags
                )

                if result.returncode != 0:
                    err_msg = result.stderr[-500:] if result.stderr else "未知错误"
                    self.error.emit(f"分组「{group_name}」合并失败:\n{err_msg}")
                    self.group_status.emit(group_name, "❌ 失败")
                    for fp in files:
                        self.file_status.emit(fp, "❌ 失败")
                    fail_count += 1
                else:
                    logger.info(f"分组「{group_name}」合并成功: {output_path}")
                    self.group_status.emit(group_name, "✅ 完成")
                    for fp in files:
                        self.file_status.emit(fp, "✅ 已合成")
                    success_count += 1

            except Exception as e:
                logger.error(f"分组「{group_name}」合并异常: {e}", exc_info=True)
                self.error.emit(f"分组「{group_name}」出错: {str(e)}")
                self.group_status.emit(group_name, "❌ 失败")
                for fp in files:
                    self.file_status.emit(fp, "❌ 失败")
                fail_count += 1
            finally:
                if concat_file and os.path.exists(concat_file):
                    try:
                        os.unlink(concat_file)
                    except:
                        pass
                for tf in txt_temp_files:
                    if tf and os.path.exists(tf):
                        try:
                            os.unlink(tf)
                        except:
                            pass

        summary = f"合并完成：成功 {success_count} 组，失败 {fail_count} 组"
        self.progress.emit(100, summary)
        self.finished.emit()

    def stop(self):
        self._is_running = False


class VideoMergerWidget(QWidget):
    """
    视频合成功能面板：支持批量拖拽多个视频，
    自动按基础名分组，同名不同序号的文件合并原地输出。
    可选在合成同时添加水印（复用主窗口的水印配置）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = []       # 所有已添加的视频路径
        self.worker = None
        self.qthread = None
        self._wm_config = None  # 由外部 (MainWindow) 注入
        self.setup_ui()

    def set_watermark_config(self, cfg: WatermarkConfig):
        """由 MainWindow 调用，传入共享的水印配置"""
        self._wm_config = cfg
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

        # 启用拖拽支持
        self.setAcceptDrops(True)

        # --- 顶部操作区 ---
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

        # --- 文件列表（增加"分组"列） ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["文件名", "分组", "大小", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # --- 合成信息提示区 ---
        match_group = QGroupBox("合成信息")
        match_layout = QVBoxLayout()

        self.lblMatchStatus = QLabel("📋 请添加视频文件（支持批量拖拽）")
        self.lblMatchStatus.setStyleSheet("padding: 8px; font-size: 13px;")
        self.lblMatchStatus.setWordWrap(True)
        match_layout.addWidget(self.lblMatchStatus)

        hint_label = QLabel(
            "💡 提示：拖拽或选择多个视频文件，系统会自动将名称相同但序号不同的文件分组合并。\n"
            "例如 clip_001.mp4、clip_002.mp4、clip_003.mp4 会自动合并为 clip_merged.mp4。\n"
            "每组至少需要 2 个文件才能合并。"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #666; font-size: 11px; padding: 4px 8px;")
        match_layout.addWidget(hint_label)

        match_group.setLayout(match_layout)
        layout.addWidget(match_group)

        # --- 水印设置（共享） ---
        wm_group = QGroupBox("水印设置")
        wm_layout = QVBoxLayout()

        self.chkAddWatermark = QCheckBox("合成时同时添加水印")
        self.chkAddWatermark.setToolTip("启用后，将使用「视频水印」标签页中配置的水印设置")
        wm_layout.addWidget(self.chkAddWatermark)

        self.lblWmStatus = QLabel("⚠️ 水印配置未加载")
        self.lblWmStatus.setStyleSheet("color: #888; padding-left: 20px;")
        wm_layout.addWidget(self.lblWmStatus)

        wm_hint_label = QLabel("💡 提示：水印参数在「视频水印」标签页的设置中统一管理。启用水印后合成需重编码，速度较慢。")
        wm_hint_label.setStyleSheet("color: #666; font-size: 11px; padding-left: 20px;")
        wm_hint_label.setWordWrap(True)
        wm_layout.addWidget(wm_hint_label)

        wm_group.setLayout(wm_layout)
        layout.addWidget(wm_group)

        # --- 控制区 ---
        ctrl_layout = QHBoxLayout()
        self.statusLabel = QLabel("准备就绪")
        ctrl_layout.addWidget(self.statusLabel)

        self.pbar = QProgressBar()
        ctrl_layout.addWidget(self.pbar)

        self.btnStart = QPushButton("▶ 开始合成")
        self.btnStart.clicked.connect(self.start_processing)
        self.btnStart.setMinimumHeight(35)
        self.btnStart.setEnabled(False)
        ctrl_layout.addWidget(self.btnStart)

        self.btnStop = QPushButton("⏹ 停止")
        self.btnStop.clicked.connect(self.stop_processing)
        self.btnStop.setEnabled(False)
        self.btnStop.setMinimumHeight(35)
        ctrl_layout.addWidget(self.btnStop)

        layout.addLayout(ctrl_layout)

    # ============================
    # 分组分析与状态更新
    # ============================

    def _update_match_status(self):
        """分析当前文件列表，更新分组信息和表格中的分组列"""
        if not self.files:
            self.lblMatchStatus.setText("📋 请添加视频文件（支持批量拖拽）")
            self.btnStart.setEnabled(False)
            return

        tasks = _build_merge_tasks(self.files)

        # 构建路径到分组名的映射
        path_to_group = {}
        for task in tasks:
            for fp in task['files']:
                path_to_group[fp] = task['group_name']

        # 更新表格中的分组列
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item:
                fp = name_item.toolTip()
                group = path_to_group.get(fp, "—")
                self.table.setItem(row, 1, QTableWidgetItem(group))

        # 统计信息
        total_files = len(self.files)
        grouped_files = sum(len(t['files']) for t in tasks)
        ungrouped = total_files - grouped_files

        if tasks:
            lines = [f"📊 共 {total_files} 个文件，检测到 {len(tasks)} 个可合并分组："]
            for t in tasks:
                lines.append(f"   • 「{t['group_name']}」: {len(t['files'])} 个文件 → {os.path.basename(t['output'])}")
            if ungrouped > 0:
                lines.append(f"   ⚠️ {ungrouped} 个文件无法分组（无同名配对），将被跳过")
            self.lblMatchStatus.setText("\n".join(lines))
            self.btnStart.setEnabled(True)
        else:
            self.lblMatchStatus.setText(
                f"📋 共 {total_files} 个文件，但未检测到可合并的分组。\n"
                "需要至少 2 个名称相同但序号不同的文件才能合并。"
            )
            self.btnStart.setEnabled(False)

    # ============================
    # 拖拽支持
    # ============================

    def dragEnterEvent(self, event):
        """拖拽进入事件：接受包含文件 URL 的拖拽"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """拖拽释放事件：提取视频文件并添加到列表"""
        urls = event.mimeData().urls()
        files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        if is_video_file(fp):
                            files.append(fp)
            elif is_video_file(path):
                files.append(path)

        if files:
            self._append_files(files)
            self.statusLabel.setText(f"已通过拖拽添加 {len(files)} 个视频文件")

    # ============================
    # 文件操作
    # ============================

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
                    fp = os.path.join(root, f)
                    if is_video_file(fp):
                        files.append(fp)
            if files:
                self._append_files(files)

    def _append_files(self, file_paths):
        """添加视频文件（无数量限制）"""
        added = 0
        for f in file_paths:
            if f in self.files:
                continue
            self.files.append(f)
            row = self.table.rowCount()
            self.table.insertRow(row)

            name_item = QTableWidgetItem(os.path.basename(f))
            name_item.setToolTip(f)  # 完整路径存储在 tooltip
            self.table.setItem(row, 0, name_item)

            # 分组列先留空，稍后由 _update_match_status 填充
            self.table.setItem(row, 1, QTableWidgetItem(""))

            try:
                size_mb = os.path.getsize(f) / (1024 * 1024)
                self.table.setItem(row, 2, QTableWidgetItem(f"{size_mb:.2f} MB"))
            except:
                self.table.setItem(row, 2, QTableWidgetItem("N/A"))

            self.table.setItem(row, 3, QTableWidgetItem("等待中"))
            added += 1

        if added > 0:
            self._update_match_status()

    def clear_list(self):
        if self.worker is not None:
            QMessageBox.warning(self, "提示", "请先停止当前任务")
            return
        self.files = []
        self.table.setRowCount(0)
        self._update_match_status()

    # ============================
    # 合成处理
    # ============================

    def start_processing(self):
        tasks = _build_merge_tasks(self.files)
        if not tasks:
            QMessageBox.warning(self, "提示", "没有可合并的文件分组")
            return

        add_watermark = self.chkAddWatermark.isChecked()
        if add_watermark and not self._wm_config:
            QMessageBox.warning(self, "提示", "水印配置未加载，请先在「视频水印」标签页中配置水印设置")
            return

        # 检查哪些输出文件已存在
        existing = [t for t in tasks if os.path.exists(t['output'])]
        if existing:
            names = "\n".join(f"  • {os.path.basename(t['output'])}" for t in existing)
            ret = QMessageBox.question(
                self, "确认",
                f"以下输出文件已存在，是否覆盖？\n{names}",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return

        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.btnAddFiles.setEnabled(False)
        self.btnAddFolder.setEnabled(False)
        self.btnClear.setEnabled(False)
        self.table.setEnabled(False)
        self.pbar.setValue(0)

        # 重置表格状态列
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 3, QTableWidgetItem("等待中"))

        # 深拷贝水印配置，防止处理过程中被主界面修改
        wm_cfg_copy = copy.deepcopy(self._wm_config) if self._wm_config else None

        # 启动后台线程
        self.qthread = QThread()
        self.worker = VideoMergerWorker(
            merge_tasks=tasks,
            wm_config=wm_cfg_copy,
            add_watermark=add_watermark
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

    # ============================
    # 信号回调
    # ============================

    def _on_progress(self, val, msg):
        self.pbar.setValue(val)
        self.statusLabel.setText(msg)

    def _on_file_status(self, file_path, status_text):
        """根据文件路径更新表格中对应行的状态列"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.toolTip() == file_path:
                self.table.setItem(row, 3, QTableWidgetItem(status_text))
                break

    def _on_error(self, msg):
        logger.error(msg)
        # 不弹窗打断流程，仅记录日志（批量模式下错误可能较多）

    def _on_finished(self):
        self.worker = None
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.btnAddFiles.setEnabled(True)
        self.btnAddFolder.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.table.setEnabled(True)

        status_text = self.statusLabel.text()
        if "成功" in status_text:
            QMessageBox.information(self, "完成", status_text)
        elif "失败" in status_text:
            QMessageBox.warning(self, "完成", status_text)

        self.statusLabel.setText("准备就绪")
