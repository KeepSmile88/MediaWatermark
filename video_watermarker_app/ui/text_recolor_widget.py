#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文字变色功能面板 Widget —— 含实时预览、蒙版可视化、参数调节。
"""
import os, sys, subprocess, cv2
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QRect, QPoint
from PySide6.QtGui import QPixmap, QColor, QImage, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QLineEdit, QGroupBox, QAbstractItemView,
    QCheckBox, QSpinBox, QComboBox, QSplitter, QColorDialog, QDoubleSpinBox,
    QTabWidget, QDialog, QDialogButtonBox, QScrollArea
)
from video_watermarker_app.core.text_recolor_worker import (
    TextRecolorWorker, VIDEO_EXTS, IMAGE_EXTS, _is_supported_file,
    _is_video, _is_image, generate_preview, extract_video_frame
)
from video_watermarker_app.utils.logger import logger


def _cv2_to_qpixmap(cv_img):
    """将 OpenCV BGR 图片转换为 QPixmap"""
    if cv_img is None:
        return QPixmap()
    h, w, ch = cv_img.shape
    rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
    qimg = QImage(rgb.data, w, h, w * ch, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class DraggablePreviewLabel(QLabel):
    """
    支持鼠标拖拽绘制矩形的预览控件。
    用户可在图片上拖拽定义蒙版区域，坐标自动映射回原始图片尺寸。
    """
    bounds_changed = Signal(int, int, int, int)  # top, bottom, left, right（原图坐标）
    double_clicked = Signal()                     # 双击信号

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self._pixmap_base = None     # 底图 QPixmap（不含矩形叠加）
        self._img_rect = QRect()     # 图片在 label 中的实际显示区域
        self._orig_w = 0             # 原始图片宽
        self._orig_h = 0             # 原始图片高
        self._dragging = False
        self._drag_start = QPoint()
        self._drag_end = QPoint()
        self._rect_defined = False   # 是否已有矩形
        self._display_rect = QRect() # 当前矩形（显示坐标）
        # 锚点拖拽状态: None / 'tl' / 'tr' / 'bl' / 'br' / 'new'
        self._drag_handle = None
        self._HANDLE_RADIUS = 8      # 锚点检测半径

    def set_preview(self, pm, orig_w, orig_h):
        """设置底图并记录原始尺寸"""
        self._pixmap_base = pm
        self._orig_w = orig_w
        self._orig_h = orig_h
        self._rect_defined = False
        self._display_rect = QRect()
        self._update_display()

    def set_bounds_overlay(self, top, bottom, left, right):
        """从外部设置蒙版矩形（原图坐标），转换为显示坐标"""
        if self._img_rect.isNull() or self._orig_w == 0:
            return
        sx = self._img_rect.width() / self._orig_w
        sy = self._img_rect.height() / self._orig_h
        ox, oy = self._img_rect.x(), self._img_rect.y()
        self._display_rect = QRect(
            int(ox + left * sx), int(oy + top * sy),
            int((right - left) * sx), int((bottom - top) * sy)
        )
        self._rect_defined = True
        self._update_display()

    # ── 锚点位置计算 ──
    def _corner_points(self):
        """返回 4 个角点的显示坐标 dict"""
        r = self._display_rect
        if r.isNull():
            return {}
        return {
            'tl': QPoint(r.left(), r.top()),
            'tr': QPoint(r.right(), r.top()),
            'bl': QPoint(r.left(), r.bottom()),
            'br': QPoint(r.right(), r.bottom()),
        }

    def _hit_handle(self, pos):
        """检测鼠标位置是否命中某个锚点，返回 handle 名称或 None"""
        if not self._rect_defined or self._display_rect.isNull():
            return None
        R = self._HANDLE_RADIUS
        for name, pt in self._corner_points().items():
            if abs(pos.x() - pt.x()) <= R and abs(pos.y() - pt.y()) <= R:
                return name
        return None

    def _cursor_for_handle(self, handle):
        """根据锚点方向返回光标"""
        cursors = {
            'tl': Qt.SizeFDiagCursor, 'br': Qt.SizeFDiagCursor,
            'tr': Qt.SizeBDiagCursor, 'bl': Qt.SizeBDiagCursor,
        }
        return cursors.get(handle, Qt.ArrowCursor)

    def _update_display(self):
        """重新合成带矩形叠加的图片"""
        if self._pixmap_base is None or self._pixmap_base.isNull():
            return
        scaled = self._pixmap_base.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x_off = (self.width() - scaled.width()) // 2
        y_off = (self.height() - scaled.height()) // 2
        self._img_rect = QRect(x_off, y_off, scaled.width(), scaled.height())

        canvas = QPixmap(self.size())
        canvas.fill(QColor("#1a1a1a"))
        painter = QPainter(canvas)
        painter.drawPixmap(x_off, y_off, scaled)

        # 画蒙版矩形
        if self._rect_defined and not self._display_rect.isNull():
            pen = QPen(QColor(255, 60, 60, 220), 2, Qt.DashLine)
            painter.setPen(pen)
            brush = QBrush(QColor(255, 60, 60, 40))
            painter.setBrush(brush)
            painter.drawRect(self._display_rect)

            # 画 4 个角点锚点
            painter.setPen(QPen(QColor(255, 255, 0, 240), 2))
            painter.setBrush(QBrush(QColor(255, 255, 0, 180)))
            R = self._HANDLE_RADIUS
            for pt in self._corner_points().values():
                painter.drawEllipse(pt, R, R)

            # 标注坐标
            bounds = self._to_orig_coords(self._display_rect)
            if bounds:
                info = f"T:{bounds[0]} B:{bounds[1]} L:{bounds[2]} R:{bounds[3]}  ({bounds[3]-bounds[2]}×{bounds[1]-bounds[0]})"
                painter.setPen(QColor(255, 255, 0, 200))
                painter.drawText(self._display_rect.left() + 4, self._display_rect.top() - 5, info)

        painter.end()
        self.setPixmap(canvas)

    def _to_orig_coords(self, display_rect):
        """显示坐标 → 原图坐标，返回 (top, bottom, left, right)"""
        if self._img_rect.isNull() or self._orig_w == 0:
            return None
        sx = self._orig_w / self._img_rect.width()
        sy = self._orig_h / self._img_rect.height()
        ox, oy = self._img_rect.x(), self._img_rect.y()
        left = max(0, int((display_rect.left() - ox) * sx))
        top = max(0, int((display_rect.top() - oy) * sy))
        right = min(self._orig_w, int((display_rect.right() - ox) * sx))
        bottom = min(self._orig_h, int((display_rect.bottom() - oy) * sy))
        return (top, bottom, left, right)

    def _clamp_to_img(self, pos):
        """将坐标限制在图片区域内"""
        x = max(self._img_rect.left(), min(pos.x(), self._img_rect.right()))
        y = max(self._img_rect.top(), min(pos.y(), self._img_rect.bottom()))
        return QPoint(x, y)

    # ── 鼠标事件 ──
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self._img_rect.isNull():
            return
        pos = event.pos()
        if not self._img_rect.contains(pos):
            return
        # 检测是否命中锚点
        handle = self._hit_handle(pos)
        if handle:
            self._dragging = True
            self._drag_handle = handle
            self._drag_start = pos
        else:
            # 新建矩形模式
            self._dragging = True
            self._drag_handle = 'new'
            self._drag_start = pos
            self._drag_end = pos

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if not self._dragging:
            # 悬停时切换光标
            handle = self._hit_handle(pos)
            if handle:
                self.setCursor(self._cursor_for_handle(handle))
            elif self._img_rect.contains(pos):
                self.setCursor(Qt.CrossCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return

        clamped = self._clamp_to_img(pos)

        if self._drag_handle == 'new':
            # 绘制新矩形
            self._drag_end = clamped
            self._display_rect = QRect(self._drag_start, self._drag_end).normalized()
            self._rect_defined = True
        else:
            # 拖拽锚点调整现有矩形
            r = QRect(self._display_rect)  # 副本
            if self._drag_handle == 'tl':
                r.setTopLeft(clamped)
            elif self._drag_handle == 'tr':
                r.setTopRight(clamped)
            elif self._drag_handle == 'bl':
                r.setBottomLeft(clamped)
            elif self._drag_handle == 'br':
                r.setBottomRight(clamped)
            self._display_rect = r.normalized()

        self._update_display()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._drag_handle = None
            if self._display_rect.width() > 5 and self._display_rect.height() > 5:
                coords = self._to_orig_coords(self._display_rect)
                if coords:
                    self.bounds_changed.emit(*coords)

    def mouseDoubleClickEvent(self, event):
        """双击打开大图弹窗"""
        if event.button() == Qt.LeftButton and self._pixmap_base is not None:
            self.double_clicked.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap_base and not self._pixmap_base.isNull():
            old_coords = None
            if self._rect_defined and not self._display_rect.isNull():
                old_coords = self._to_orig_coords(self._display_rect)
            self._update_display()
            if old_coords:
                self.set_bounds_overlay(*old_coords)

    def get_current_bounds(self):
        """获取当前蒙版的原图坐标，无则返回 None"""
        if self._rect_defined and not self._display_rect.isNull():
            return self._to_orig_coords(self._display_rect)
        return None


class MaskDetailDialog(QDialog):
    """
    蒙版大图弹窗 —— 独立窗口，方便精细调整蒙版矩形。
    内含大尺寸 DraggablePreviewLabel，关闭时返回调整后的蒙版坐标。
    """
    bounds_confirmed = Signal(int, int, int, int)  # top, bottom, left, right

    def __init__(self, pixmap_base, orig_w, orig_h, init_bounds=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("蒙版区域调整 — 拖拽矩形调整蒙版范围")
        self.setMinimumSize(800, 900)
        self.resize(min(orig_w + 80, 1200), min(orig_h + 120, 1080))
        self._result_bounds = init_bounds

        layout = QVBoxLayout(self)

        # 提示文字
        tip = QLabel("💡 在图片上拖拽鼠标绘制蒙版区域，松开鼠标后坐标自动更新")
        tip.setStyleSheet("color:#999;font-size:12px;padding:4px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # 大图拖拽控件
        self.preview = DraggablePreviewLabel()
        self.preview.setMinimumSize(700, 700)
        self.preview.setStyleSheet("background:#111;border:1px solid #333;")
        self.preview.set_preview(pixmap_base, orig_w, orig_h)
        if init_bounds:
            self.preview.set_bounds_overlay(*init_bounds)
        self.preview.bounds_changed.connect(self._on_bounds_changed)
        layout.addWidget(self.preview, 1)

        # 坐标信息
        self.lblInfo = QLabel(self._format_bounds(init_bounds))
        self.lblInfo.setStyleSheet("color:#ccc;font-size:13px;padding:4px;font-family:monospace;")
        layout.addWidget(self.lblInfo)

        # 按钮
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_bounds_changed(self, top, bottom, left, right):
        self._result_bounds = (top, bottom, left, right)
        self.lblInfo.setText(self._format_bounds(self._result_bounds))

    def _format_bounds(self, bounds):
        if bounds is None:
            return "蒙版区域: 未定义（请拖拽绘制）"
        t, b, l, r = bounds
        return f"蒙版区域:  上={t}  下={b}  左={l}  右={r}  |  宽={r-l}  高={b-t}"

    def _on_accept(self):
        if self._result_bounds:
            self.bounds_confirmed.emit(*self._result_bounds)
        self.accept()

    def get_bounds(self):
        return self._result_bounds


class TextRecolorWidget(QWidget):
    """文字变色功能面板（含实时预览）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = []
        self.worker = None
        self.qthread = None
        self._current_color = '#6600CC'
        self._preview_frame = None          # 原始帧 BGR numpy
        self._preview_source_path = None    # 当前预览对应的文件路径
        self._preview_timer = QTimer()      # 防抖定时器
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(300)
        self._preview_timer.timeout.connect(self._do_refresh_preview)
        self.setup_ui()

    # ══════════════════════════════════════════════════
    #  UI 构建
    # ══════════════════════════════════════════════════
    def setup_ui(self):
        root = QVBoxLayout(self)
        self.setAcceptDrops(True)

        # 顶部操作栏
        top = QHBoxLayout()
        self.btnAddFiles = QPushButton("📄 添加文件")
        self.btnAddFiles.clicked.connect(self.add_files)
        top.addWidget(self.btnAddFiles)
        self.btnAddFolder = QPushButton("📁 添加文件夹")
        self.btnAddFolder.clicked.connect(self.add_folder)
        top.addWidget(self.btnAddFolder)
        self.btnClear = QPushButton("🗑️ 清空列表")
        self.btnClear.clicked.connect(self.clear_list)
        top.addWidget(self.btnClear)
        top.addStretch()
        root.addLayout(top)

        # ═══ 主区域 Splitter：左(列表) + 右(预览) ═══
        main_splitter = QSplitter(Qt.Horizontal)

        # —— 左侧：文件列表 ——
        left_w = QWidget()
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_lay.addWidget(self.table)
        main_splitter.addWidget(left_w)

        # —— 右侧：预览区（三Tab切换） ——
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0)

        self.previewTabs = QTabWidget()
        # 原图
        self.lblOriginal = QLabel("选择文件后显示原图")
        self.lblOriginal.setAlignment(Qt.AlignCenter)
        self.lblOriginal.setMinimumSize(320, 420)
        self.lblOriginal.setStyleSheet("background:#1a1a1a;border-radius:6px;color:#888;")
        self.previewTabs.addTab(self.lblOriginal, "📷 原图")
        # 蒙版（可拖拽）
        self.lblMask = DraggablePreviewLabel("选择文件后显示蒙版检测")
        self.lblMask.setMinimumSize(320, 420)
        self.lblMask.setStyleSheet("background:#1a1a1a;border-radius:6px;color:#888;")
        self.lblMask.bounds_changed.connect(self._on_drag_bounds_changed)
        self.lblMask.double_clicked.connect(self._open_mask_detail)
        self.previewTabs.addTab(self.lblMask, "🎭 蒙版区域 (可拖拽/双击放大)")
        # 效果
        self.lblResult = QLabel("选择文件后显示变色效果")
        self.lblResult.setAlignment(Qt.AlignCenter)
        self.lblResult.setMinimumSize(320, 420)
        self.lblResult.setStyleSheet("background:#1a1a1a;border-radius:6px;color:#888;")
        self.previewTabs.addTab(self.lblResult, "🎨 变色效果")

        right_lay.addWidget(self.previewTabs, 1)

        # 预览信息
        self.lblPreviewInfo = QLabel("")
        self.lblPreviewInfo.setStyleSheet("color:#999;font-size:11px;padding:2px 4px;")
        self.lblPreviewInfo.setWordWrap(True)
        right_lay.addWidget(self.lblPreviewInfo)

        # 刷新按钮
        self.btnRefresh = QPushButton("🔄 刷新预览")
        self.btnRefresh.clicked.connect(self._do_refresh_preview)
        right_lay.addWidget(self.btnRefresh)

        main_splitter.addWidget(right_w)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 4)
        root.addWidget(main_splitter, 1)

        # ═══ 参数设置 ═══
        sg = QGroupBox("变色参数")
        sl = QVBoxLayout()

        # 行1：颜色 + 模式
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("目标颜色:"))
        self.btnColorPicker = QPushButton()
        self.btnColorPicker.setFixedSize(80, 28)
        self._update_color_button()
        self.btnColorPicker.clicked.connect(self._pick_color)
        r1.addWidget(self.btnColorPicker)
        self.lblColorHex = QLabel(self._current_color)
        self.lblColorHex.setStyleSheet("color:#aaa;font-size:12px;")
        r1.addWidget(self.lblColorHex)
        r1.addSpacing(20)
        r1.addWidget(QLabel("变色模式:"))
        self.cmbMode = QComboBox()
        self.cmbMode.addItem("通用变色 (Lab)", "lab_colorize")
        self.cmbMode.addItem("仅改文字 (Text Only)", "text_only")
        self.cmbMode.setFixedWidth(200)
        self.cmbMode.currentIndexChanged.connect(self._schedule_preview)
        r1.addWidget(self.cmbMode)
        r1.addStretch()
        sl.addLayout(r1)

        # 行2：强度 + 羽化 + 蒙版参数
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("强度:"))
        self.spinStrength = QDoubleSpinBox()
        self.spinStrength.setRange(0.1, 1.0)
        self.spinStrength.setValue(0.85)
        self.spinStrength.setSingleStep(0.05)
        self.spinStrength.setFixedWidth(200)
        self.spinStrength.valueChanged.connect(self._schedule_preview)
        self.spinStrength.setStyleSheet("")
        r2.addWidget(self.spinStrength)
        r2.addWidget(QLabel("羽化:"))
        self.spinFeather = QSpinBox()
        self.spinFeather.setRange(1, 50)
        self.spinFeather.setValue(15)
        self.spinFeather.setFixedWidth(200)
        self.spinFeather.setSuffix(" px")
        self.spinFeather.setStyleSheet("")
        self.spinFeather.valueChanged.connect(self._schedule_preview)
        r2.addWidget(self.spinFeather)
        r2.addWidget(QLabel("蒙版亮度:"))
        self.spinBrightness = QSpinBox()
        self.spinBrightness.setRange(100, 255)
        self.spinBrightness.setValue(185)
        self.spinBrightness.setFixedWidth(200)
        self.spinBrightness.valueChanged.connect(self._schedule_preview)
        r2.addWidget(self.spinBrightness)
        r2.addWidget(QLabel("均匀度:"))
        self.spinStdThresh = QSpinBox()
        self.spinStdThresh.setRange(10, 100)
        self.spinStdThresh.setValue(35)
        self.spinStdThresh.setFixedWidth(200)
        self.spinStdThresh.valueChanged.connect(self._schedule_preview)
        r2.addWidget(self.spinStdThresh)
        r2.addStretch()
        sl.addLayout(r2)

        # 行3：手动蒙版
        r3 = QHBoxLayout()
        self.chkManualBounds = QCheckBox("手动蒙版区域")
        self.chkManualBounds.toggled.connect(self._on_manual_bounds_toggled)
        r3.addWidget(self.chkManualBounds)
        self.spinTop = QSpinBox(); self.spinTop.setRange(0,9999); self.spinTop.setFixedWidth(100); self.spinTop.setEnabled(False)
        self.spinBottom = QSpinBox(); self.spinBottom.setRange(0,9999); self.spinBottom.setFixedWidth(100); self.spinBottom.setEnabled(False)
        self.spinLeft = QSpinBox(); self.spinLeft.setRange(0,9999); self.spinLeft.setFixedWidth(100); self.spinLeft.setEnabled(False)
        self.spinRight = QSpinBox(); self.spinRight.setRange(0,9999); self.spinRight.setFixedWidth(100); self.spinRight.setEnabled(False)
        for lbl, sp in [("上:", self.spinTop), ("下:", self.spinBottom), ("左:", self.spinLeft), ("右:", self.spinRight)]:
            r3.addWidget(QLabel(lbl)); r3.addWidget(sp)
            sp.setStyleSheet("")
            sp.valueChanged.connect(self._schedule_preview)
        r3.addStretch()
        sl.addLayout(r3)

        # 行4：输出目录
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("输出目录:"))
        self.edtOutputDir = QLineEdit()
        self.edtOutputDir.setPlaceholderText("选择保存变色结果的目录...")
        self.edtOutputDir.setReadOnly(True)
        r4.addWidget(self.edtOutputDir)
        self.btnSelectOutput = QPushButton("选择...")
        self.btnSelectOutput.clicked.connect(self.select_output_dir)
        r4.addWidget(self.btnSelectOutput)
        self.btnOpenOutput = QPushButton("📂 打开")
        self.btnOpenOutput.clicked.connect(self.open_output_dir)
        r4.addWidget(self.btnOpenOutput)
        sl.addLayout(r4)

        sg.setLayout(sl)
        root.addWidget(sg)

        # ═══ 底部控制区 ═══
        ctrl = QHBoxLayout()
        self.statusLabel = QLabel("准备就绪")
        ctrl.addWidget(self.statusLabel)
        self.pbar = QProgressBar()
        ctrl.addWidget(self.pbar)
        self.btnStart = QPushButton("▶ 开始处理")
        self.btnStart.clicked.connect(self.start_processing)
        self.btnStart.setMinimumHeight(35)
        ctrl.addWidget(self.btnStart)
        self.btnStop = QPushButton("⏹ 停止")
        self.btnStop.clicked.connect(self.stop_processing)
        self.btnStop.setEnabled(False)
        self.btnStop.setMinimumHeight(35)
        ctrl.addWidget(self.btnStop)
        root.addLayout(ctrl)

    # ══════════════════════════════════════════════════
    #  预览相关
    # ══════════════════════════════════════════════════
    def _schedule_preview(self):
        """参数变更后防抖刷新预览"""
        if self._preview_frame is not None:
            self._preview_timer.start()

    def _on_selection_changed(self):
        """列表选中项变化时加载帧并刷新预览"""
        items = self.table.selectedItems()
        if not items:
            return
        row = items[0].row()
        name_item = self.table.item(row, 0)
        if not name_item:
            return
        file_path = name_item.data(Qt.UserRole)
        if file_path == self._preview_source_path:
            return
        self._preview_source_path = file_path
        self._load_frame(file_path)

    def _load_frame(self, file_path):
        """加载图片或视频帧"""
        self.statusLabel.setText(f"加载预览: {os.path.basename(file_path)}...")
        try:
            if _is_image(file_path):
                self._preview_frame = cv2.imread(str(file_path))
            elif _is_video(file_path):
                self._preview_frame = extract_video_frame(file_path, frame_sec=1.0)
            else:
                self._preview_frame = None

            if self._preview_frame is not None:
                h, w = self._preview_frame.shape[:2]
                self.lblPreviewInfo.setText(f"文件: {os.path.basename(file_path)}  |  尺寸: {w}×{h}")
                # 如果手动蒙版未勾选，自动检测后回填坐标
                self._do_refresh_preview()
            else:
                self._clear_preview("无法加载文件")
        except Exception as e:
            logger.error(f"加载预览失败: {e}")
            self._clear_preview(f"加载失败: {e}")

    def _do_refresh_preview(self):
        """执行预览刷新（生成三张图）"""
        if self._preview_frame is None:
            return

        fixed_bounds = None
        if self.chkManualBounds.isChecked():
            fixed_bounds = dict(
                top=self.spinTop.value(), bottom=self.spinBottom.value(),
                left=self.spinLeft.value(), right=self.spinRight.value()
            )

        try:
            original, mask_ov, result, bounds = generate_preview(
                self._preview_frame,
                color=self._current_color,
                mode=self.cmbMode.currentData(),
                strength=self.spinStrength.value(),
                feather=self.spinFeather.value(),
                std_threshold=self.spinStdThresh.value(),
                brightness_threshold=self.spinBrightness.value(),
                fixed_bounds=fixed_bounds,
            )
            # 如果非手动模式，回填自动检测到的蒙版坐标
            if bounds and not self.chkManualBounds.isChecked():
                self._fill_bounds_silent(bounds)

            orig_h, orig_w = self._preview_frame.shape[:2]

            self._show_pixmap(self.lblOriginal, original)
            # 蒙版Tab：使用 DraggablePreviewLabel 的专用方法
            pm_mask = _cv2_to_qpixmap(mask_ov)
            self.lblMask.set_preview(pm_mask, orig_w, orig_h)
            # 在拖拽预览上显示当前蒙版边界
            if bounds:
                self.lblMask.set_bounds_overlay(
                    bounds['top'], bounds['bottom'],
                    bounds['left'], bounds['right']
                )
            self._show_pixmap(self.lblResult, result)
            self.statusLabel.setText("预览已更新 — 在蒙版Tab上拖拽可调整区域")
        except Exception as e:
            logger.error(f"预览生成失败: {e}")
            self.statusLabel.setText(f"预览失败: {e}")

    def _open_mask_detail(self):
        """双击蒙版预览，打开大图弹窗精细调整"""
        if self._preview_frame is None or self.lblMask._pixmap_base is None:
            return

        orig_h, orig_w = self._preview_frame.shape[:2]
        # 获取当前蒙版坐标
        init_bounds = self.lblMask.get_current_bounds()

        dlg = MaskDetailDialog(
            pixmap_base=self.lblMask._pixmap_base,
            orig_w=orig_w,
            orig_h=orig_h,
            init_bounds=init_bounds,
            parent=self,
        )
        dlg.bounds_confirmed.connect(self._on_drag_bounds_changed)
        dlg.exec()

    def _on_drag_bounds_changed(self, top, bottom, left, right):
        """用户在蒙版预览上拖拽完成，更新手动蒙版坐标并刷新预览"""
        # 自动勾选手动蒙版
        self.chkManualBounds.blockSignals(True)
        self.chkManualBounds.setChecked(True)
        self.chkManualBounds.blockSignals(False)
        for sp in (self.spinTop, self.spinBottom, self.spinLeft, self.spinRight):
            sp.setEnabled(True)
        self._fill_bounds_silent(dict(top=top, bottom=bottom, left=left, right=right))
        self._do_refresh_preview()

    def _fill_bounds_silent(self, bounds):
        """静默回填蒙版坐标（不触发信号）"""
        for sp, key in [(self.spinTop,'top'),(self.spinBottom,'bottom'),(self.spinLeft,'left'),(self.spinRight,'right')]:
            sp.blockSignals(True)
            sp.setValue(bounds.get(key, 0))
            sp.blockSignals(False)

    def _show_pixmap(self, label, cv_img):
        """在 QLabel 上显示 OpenCV 图片，自适应尺寸"""
        pm = _cv2_to_qpixmap(cv_img)
        if pm.isNull():
            return
        scaled = pm.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(scaled)
        label.setText("")

    def _clear_preview(self, msg="选择文件后显示预览"):
        self._preview_frame = None
        self._preview_source_path = None
        for lbl in (self.lblOriginal, self.lblMask, self.lblResult):
            lbl.setPixmap(QPixmap())
            lbl.setText(msg)
        self.lblPreviewInfo.setText("")

    # ══════════════════════════════════════════════════
    #  颜色选择
    # ══════════════════════════════════════════════════
    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self._current_color), self, "选择目标文字颜色")
        if color.isValid():
            self._current_color = color.name()
            self._update_color_button()
            self.lblColorHex.setText(self._current_color)
            self._schedule_preview()

    def _update_color_button(self):
        self.btnColorPicker.setStyleSheet(
            f"background-color:{self._current_color};border:2px solid #555;border-radius:4px;"
        )

    # ══════════════════════════════════════════════════
    #  手动蒙版切换
    # ══════════════════════════════════════════════════
    def _on_manual_bounds_toggled(self, checked):
        for sp in (self.spinTop, self.spinBottom, self.spinLeft, self.spinRight):
            sp.setEnabled(checked)
        self._schedule_preview()

    # ══════════════════════════════════════════════════
    #  拖拽支持
    # ══════════════════════════════════════════════════
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        files = []
        first_dir = None
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                if first_dir is None: first_dir = path
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        if _is_supported_file(fp): files.append(fp)
            elif _is_supported_file(path):
                if first_dir is None: first_dir = os.path.dirname(path)
                files.append(path)
        if files:
            self._append_files(files)
            if not self.edtOutputDir.text().strip() and first_dir:
                self.edtOutputDir.setText(first_dir)

    # ══════════════════════════════════════════════════
    #  文件管理
    # ══════════════════════════════════════════════════
    def add_files(self):
        f_str = ("媒体文件 (*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm *.ts "
                 "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif);;All Files (*)")
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", f_str)
        if files: self._append_files(files)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d:
            files = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs if _is_supported_file(os.path.join(r, f))]
            if files:
                self._append_files(files)
                if not self.edtOutputDir.text().strip(): self.edtOutputDir.setText(d)

    def _append_files(self, file_paths):
        for f in file_paths:
            if f not in self.files:
                self.files.append(f)
                row = self.table.rowCount()
                self.table.insertRow(row)
                ni = QTableWidgetItem(os.path.basename(f))
                ni.setToolTip(f); ni.setData(Qt.UserRole, f)
                self.table.setItem(row, 0, ni)
                self.table.setItem(row, 1, QTableWidgetItem(os.path.splitext(f)[1].upper().replace(".","")))
                try: self.table.setItem(row, 2, QTableWidgetItem(f"{os.path.getsize(f)/1048576:.2f} MB"))
                except: self.table.setItem(row, 2, QTableWidgetItem("N/A"))
                self.table.setItem(row, 3, QTableWidgetItem("等待中"))

    def clear_list(self):
        if self.worker is not None:
            QMessageBox.warning(self, "提示", "请先停止当前任务"); return
        self.files = []; self.table.setRowCount(0); self._clear_preview()

    # ══════════════════════════════════════════════════
    #  输出目录
    # ══════════════════════════════════════════════════
    def select_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d: self.edtOutputDir.setText(d)

    def open_output_dir(self):
        d = self.edtOutputDir.text().strip()
        if not d or not os.path.isdir(d):
            QMessageBox.warning(self, "提示", "输出目录不存在"); return
        if sys.platform=='win32': os.startfile(d)
        elif sys.platform=='darwin': subprocess.Popen(['open',d])
        else: subprocess.Popen(['xdg-open',d])

    # ══════════════════════════════════════════════════
    #  处理控制
    # ══════════════════════════════════════════════════
    def start_processing(self):
        if not self.files:
            QMessageBox.warning(self, "提示", "请先添加文件"); return
        output_dir = self.edtOutputDir.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "提示", "请选择输出目录"); return
        os.makedirs(output_dir, exist_ok=True)

        fixed_bounds = None
        if self.chkManualBounds.isChecked():
            fixed_bounds = dict(top=self.spinTop.value(), bottom=self.spinBottom.value(),
                                left=self.spinLeft.value(), right=self.spinRight.value())

        self.btnStart.setEnabled(False); self.btnStop.setEnabled(True)
        self.table.setEnabled(False); self.pbar.setValue(0)
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 3, QTableWidgetItem("等待中"))

        self.qthread = QThread()
        self.worker = TextRecolorWorker(
            file_paths=list(self.files), output_dir=output_dir,
            color=self._current_color, mode=self.cmbMode.currentData(),
            strength=self.spinStrength.value(), feather=self.spinFeather.value(),
            std_threshold=self.spinStdThresh.value(),
            brightness_threshold=self.spinBrightness.value(),
            fixed_bounds=fixed_bounds,
        )
        self.worker.moveToThread(self.qthread)
        self.qthread.started.connect(self.worker.run)
        self.worker.finished.connect(self.qthread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.qthread.finished.connect(self.qthread.deleteLater)
        self.qthread.finished.connect(self._on_finished)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_status.connect(self._on_file_status)
        self.worker.file_progress.connect(self._on_file_progress)
        self.worker.error.connect(self._on_error)
        self.qthread.start()

    def stop_processing(self):
        if self.worker: self.worker.stop()
        self.btnStop.setEnabled(False); self.statusLabel.setText("正在停止...")

    def _on_progress(self, val, msg):
        self.pbar.setValue(val); self.statusLabel.setText(msg)

    def _on_file_status(self, idx, text):
        if 0 <= idx < self.table.rowCount():
            self.table.setItem(idx, 3, QTableWidgetItem(text))

    def _on_file_progress(self, idx, pct):
        if 0 <= idx < self.table.rowCount():
            self.table.setItem(idx, 3, QTableWidgetItem(f"🔄 {pct}%"))

    def _on_error(self, msg):
        logger.error(msg); QMessageBox.warning(self, "错误", msg)

    def _on_finished(self):
        self.worker = None
        self.btnStart.setEnabled(True); self.btnStop.setEnabled(False)
        self.table.setEnabled(True); self.pbar.setValue(100)
        self.statusLabel.setText("任务完成")
        QMessageBox.information(self, "完成", "所有文字变色任务已完成！")

    # ══════════════════════════════════════════════════
    #  键盘事件
    # ══════════════════════════════════════════════════
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            for row in sorted(set(i.row() for i in self.table.selectedIndexes()), reverse=True):
                fp = self.table.item(row, 0).data(Qt.UserRole)
                if fp in self.files: self.files.remove(fp)
                self.table.removeRow(row)
        else:
            super().keyPressEvent(event)
