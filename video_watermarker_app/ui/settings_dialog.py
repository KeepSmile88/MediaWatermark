#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from video_watermarker_app.ui.ui_settings_dialog import Ui_SettingsDialog
from video_watermarker_app.utils.config import AppConfig, WatermarkConfig
from video_watermarker_app.utils.common import get_available_encoders
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QListWidgetItem, QFontDialog, QMessageBox, 
    QInputDialog, QLabel, QPushButton, QCheckBox, QHBoxLayout, QColorDialog,
    QVBoxLayout, QTabWidget, QWidget, QComboBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QGroupBox, QFormLayout
)
from PySide6.QtGui import QColor, QFont, QFontInfo
from PySide6.QtCore import Signal


class SettingsDialog(QDialog, Ui_SettingsDialog):
    config_changed = Signal(WatermarkConfig)

    def __init__(self, parent=None, advanced_mode=False):
        super().__init__(parent)
        self.setupUi(self)
        
        self.app_config = AppConfig()
        self._is_loading = True
        self._advanced_mode = advanced_mode
        self._extra_wm_tabs = []  # 存储额外水印层的 UI 控件引用
        # --- 动态添加颜色设置 ---
        self.label_color = QLabel("文字颜色")
        self.btnSelectColor = QPushButton("#FFFFFF")
        self.btnSelectColor.setFixedWidth(100)
        self.chkAutoColor = QCheckBox("智能选色")
        self.chkAutoColor.setToolTip("取第5帧画面计算补色，自动调整文字颜色与描边")
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(self.btnSelectColor)
        color_layout.addWidget(self.chkAutoColor)
        color_layout.addStretch()
        
        # 插入到 formLayoutWm 中
        # 根据 settings.ui，插在位置(row 2)之后，即 row 3。
        self.formLayoutWm.insertRow(3, self.label_color, color_layout)
        
        # --- 动态添加背景颜色设置 ---
        self.label_bg_color = QLabel("背景颜色")
        self.chkBgEnabled = QCheckBox("启用背景")
        self.chkBgEnabled.setToolTip("为水印文字添加背景色块")
        self.btnSelectBgColor = QPushButton("#000000")
        self.btnSelectBgColor.setFixedWidth(100)
        self.btnSelectBgColor.setStyleSheet(
            "background-color: #000000; color: white; border: 1px solid gray;"
        )
        
        bg_color_layout = QHBoxLayout()
        bg_color_layout.addWidget(self.chkBgEnabled)
        bg_color_layout.addWidget(self.btnSelectBgColor)
        bg_color_layout.addStretch()
        
        # 插入到文字颜色行之后 (row 4)
        self.formLayoutWm.insertRow(4, self.label_bg_color, bg_color_layout)
        
        # --- 动态添加居中Y偏移 ---
        self.label_center_y_offset = QLabel("居中Y偏移")
        self.spnCenterYOffset = QSpinBox()
        self.spnCenterYOffset.setRange(-2000, 2000)
        self.spnCenterYOffset.setSingleStep(10)
        self.spnCenterYOffset.setValue(0)
        self.spnCenterYOffset.setSuffix(" px")
        self.spnCenterYOffset.setToolTip("居中/上中/下中位置时的垂直偏移（正值下移，负值上移）\n设置后优先级高于自动避让")
        self.formLayoutWm.insertRow(5, self.label_center_y_offset, self.spnCenterYOffset)
        
        # 信号绑定
        self.btnSelectColor.clicked.connect(self._select_color)
        self.chkAutoColor.stateChanged.connect(self._emit_config)
        self.btnSelectBgColor.clicked.connect(self._select_bg_color)
        self.chkBgEnabled.stateChanged.connect(self._emit_config)
        self.spnCenterYOffset.valueChanged.connect(self._emit_config)

        # --- 动态添加基本设置功能 ---
        self.chkInplace = QCheckBox("处理后原地替换原文件 (慎用)")
        self.chkInplace.setToolTip("开启后将覆盖原始视频/图片，建议开启前确认设置无误")
        # 插入到 formLayoutBasic，放在“输出到源文件同目录”之后
        self.formLayoutBasic.insertRow(2, "", self.chkInplace)
        
        self.chkLossless = QCheckBox("全保真 (处理 JPG 时转为 PNG)")
        self.chkLossless.setToolTip("开启后，即使输入是 JPG 格式图片，软件也默认以 PNG 的逻辑处理以解决失真问题")
        self.formLayoutBasic.insertRow(3, "", self.chkLossless)

        self.label_opacity.setText("不透明度(0-1)")

        self.cmbType.setCurrentIndex(2)

        # 加载上次配置
        self.current_cfg = self.app_config.load_last_config()
        
        # 初始化 UI 状态
        self._load_from_config(self.current_cfg)
        
        # 信号绑定
        self.listNav.currentRowChanged.connect(self.stackedWidget.setCurrentIndex)
        self.btnBrowseOut.clicked.connect(self._browse_out)
        self.btnBrowseWm.clicked.connect(self._browse_wm)
        self.chkSameDir.stateChanged.connect(self._toggle_out_dir)
        self.cmbType.currentIndexChanged.connect(self._toggle_wm_type)
        self.cmbBuiltin.currentIndexChanged.connect(self._on_builtin_changed)
        
        self.btnSaveTemplate.clicked.connect(self._save_template)
        self.btnDelTemplate.clicked.connect(self._delete_template)
        self.cmbTemplates.currentIndexChanged.connect(self._on_template_selected)
        self.chkInplace.stateChanged.connect(self._toggle_out_dir)
        self.chkLossless.stateChanged.connect(self._emit_config)
        
        # 实时预览触发信号
        for widget in [self.cmbType, self.cmbPosition, self.cmbPreset, self.cmbExt, self.cmbBuiltin]:
             widget.currentIndexChanged.connect(self._emit_config)
        for widget in [self.spnOpacity, self.spnScale, self.spnMargin, self.spnCrf, self.spnFeather, self.spnConcurrent]:
             widget.valueChanged.connect(self._emit_config)
        self.chkGpu.stateChanged.connect(self._emit_config)
        self.edtWmContent.textChanged.connect(self._on_content_changed)
        self.btnSelectFont.clicked.connect(self._select_font)
        
        self._check_gpu_support()
        self._refresh_templates()
        
        # 恢复上次选中的模板
        last_tpl = self.app_config.get_last_template_name()
        if last_tpl:
            idx = self.cmbTemplates.findText(last_tpl)
            if idx > 0:
                self.cmbTemplates.blockSignals(True)
                self.cmbTemplates.setCurrentIndex(idx)
                self.cmbTemplates.blockSignals(False)

        self._is_loading = False
        self._toggle_out_dir()
        self._toggle_wm_type()

        # --- 高级模式：多水印面板 ---
        if self._advanced_mode:
            self._build_multi_watermark_panel()

    def _load_from_config(self, cfg: WatermarkConfig):
        was_loading = self._is_loading
        self._is_loading = True
        # 暂时阻塞所有重要控件的信号，防止配置加载时的中间态触发不完整的 sync/update
        widgets_to_block = [
            self.cmbType, self.cmbPosition, self.cmbPreset, self.cmbExt, self.cmbBuiltin,
            self.spnOpacity, self.spnScale, self.spnMargin, self.spnCrf, self.spnFeather,
            self.spnConcurrent, self.chkGpu, self.chkSameDir, self.chkAutoColor, self.chkInplace,
            self.chkBgEnabled, self.spnCenterYOffset, self.chkLossless
        ]
        for w in widgets_to_block: w.blockSignals(True)
        
        try:
            # 同步备份当前的完整配置，确保 get_config 能拿到 non-UI 字段 (如 font_path)
            self.current_cfg = cfg

            self.edtOutDir.setText(cfg.output_dir)
            self.chkSameDir.setChecked(cfg.same_dir)
            self.chkInplace.setChecked(cfg.inplace_replace)
            self.chkLossless.setChecked(cfg.lossless_image)

            idx_type = 0 if cfg.wm_type == "image" else 1
            self.cmbType.setCurrentIndex(idx_type)
            if cfg.wm_type == "image":
                self.edtWmContent.setText(cfg.image_path)
                self._set_builtin_from_path(cfg.image_path)
            else:
                self.edtWmContent.setText(cfg.text)
                
            self.cmbPosition.setCurrentText(cfg.position)
            self.spnOpacity.setValue(cfg.opacity)
            self.spnScale.setValue(cfg.image_scale_pct if cfg.wm_type == "image" else cfg.text_size_pct)
            self.spnMargin.setValue(cfg.margin)
            self.spnFeather.setValue(cfg.feather_radius)
            if cfg.font_name:
                self.btnSelectFont.setText(f"字体: {cfg.font_name}")
            else:
                self.btnSelectFont.setText("选择字体...")

            self.btnSelectColor.setText(cfg.font_color)
            q_col = QColor(cfg.font_color)
            if not q_col or not q_col.isValid(): q_col = QColor("#FFFFFF")
            self.btnSelectColor.setStyleSheet(
                f"background-color: {q_col.name()}; color: {'black' if q_col.lightness() > 128 else 'white'}; border: 1px solid gray;"
            )
            self.chkAutoColor.setChecked(cfg.auto_color)

            # 背景色
            self.chkBgEnabled.setChecked(cfg.bg_enabled)
            self.btnSelectBgColor.setText(cfg.bg_color or "#000000")
            bg_col = QColor(cfg.bg_color or "#000000")
            if bg_col.isValid():
                self.btnSelectBgColor.setStyleSheet(
                    f"background-color: {bg_col.name()}; color: {'black' if bg_col.lightness() > 128 else 'white'}; border: 1px solid gray;"
                )

            # 居中Y偏移
            self.spnCenterYOffset.setValue(cfg.center_y_offset)

            self.spnCrf.setValue(cfg.crf)
            self.cmbPreset.setCurrentText(cfg.preset)
            self.cmbExt.setCurrentText(cfg.out_ext)
            self.chkGpu.setChecked(cfg.gpu_enabled)
            self.spnConcurrent.setValue(cfg.max_concurrent)
        finally:
            for w in widgets_to_block: w.blockSignals(False)
            self.edtWmContent.blockSignals(False)
            
        # 手动同步界面状态（可见性等）
        self._toggle_out_dir()
        self._toggle_wm_type()
        
        # 恢复状态
        self._is_loading = was_loading

    def _refresh_templates(self):
        self.cmbTemplates.blockSignals(True)
        self.cmbTemplates.clear()
        self.cmbTemplates.addItem("-- 选择模板 --")
        templates = self.app_config.get_templates()
        for name in templates.keys():
            self.cmbTemplates.addItem(name)
        self.cmbTemplates.blockSignals(False)

    def _check_gpu_support(self):
        encoders = get_available_encoders()
        if not encoders:
            self.chkGpu.setEnabled(False)
            self.chkGpu.setToolTip("未检测到兼容的 GPU 硬件加速编码器")
        else:
            self.chkGpu.setToolTip(f"检测到可用编码器: {', '.join(encoders)}")

    def get_config(self) -> WatermarkConfig:
        """从 UI 收集配置并在 accept 时保存"""
        cfg = WatermarkConfig()

        cfg.output_dir = self.edtOutDir.text()
        cfg.same_dir = self.chkSameDir.isChecked()
        cfg.inplace_replace = self.chkInplace.isChecked()
        cfg.lossless_image = self.chkLossless.isChecked()

        is_image = (self.cmbType.currentIndex() == 0)
        cfg.wm_type = "image" if is_image else "text"
        if is_image:
            cfg.image_path = self.edtWmContent.text()
        else:
            cfg.text = self.edtWmContent.text()
            
        cfg.position = self.cmbPosition.currentText()
        cfg.opacity = self.spnOpacity.value()
        
        val_scale = self.spnScale.value()
        if is_image:
            cfg.image_scale_pct = val_scale
            cfg.text_size_pct = self.current_cfg.text_size_pct
        else:
            cfg.text_size_pct = val_scale
            cfg.image_scale_pct = self.current_cfg.image_scale_pct
            
        cfg.margin = self.spnMargin.value()
        cfg.feather_radius = self.spnFeather.value()
        
        # 补全坐标 (虽然 UI 可能没放，但要保留从 current_cfg 载入的值或默认值)
        cfg.custom_x = self.current_cfg.custom_x
        cfg.custom_y = self.current_cfg.custom_y
        
        # 居中Y偏移
        cfg.center_y_offset = self.spnCenterYOffset.value()
        
        # 字体
        cfg.font_path = self.current_cfg.font_path
        cfg.font_name = self.current_cfg.font_name

        cfg.crf = self.spnCrf.value()
        cfg.preset = self.cmbPreset.currentText()
        cfg.out_ext = self.cmbExt.currentText()
        cfg.gpu_enabled = self.chkGpu.isChecked()
        cfg.max_concurrent = self.spnConcurrent.value()

        cfg.font_color = self.btnSelectColor.text()
        cfg.auto_color = self.chkAutoColor.isChecked()
        cfg.border_color = self.current_cfg.border_color
        
        # 背景色
        cfg.bg_enabled = self.chkBgEnabled.isChecked()
        cfg.bg_color = self.btnSelectBgColor.text()
        
        return cfg

    def _on_content_changed(self, text):
        is_image = (self.cmbType.currentIndex() == 0)
        if is_image:
            self._set_builtin_from_path(text)
        else:
            texts = {
                2: "Imagine create de AI",
                3: "Generat cu AI"
            }
            found = 0
            for idx, val in texts.items():
                if text == val:
                    found = idx
                    break

            self.cmbBuiltin.blockSignals(True)
            self.cmbBuiltin.setCurrentIndex(found)
            self.cmbBuiltin.blockSignals(False)
        
        self._emit_config()

    def _emit_config(self, *args):
        """发射配置更改信号，供主界面实时预览"""
        self.config_changed.emit(self.get_config())

    def _build_multi_watermark_panel(self):
        """构建多水印 Tab 面板，添加到设置导航中"""
        # 在 listNav 中添加一个新条目
        self.listNav.addItem("🎨 多水印")

        self.multi_wm_page = QWidget()
        page_layout = QVBoxLayout(self.multi_wm_page)

        header = QLabel("🔓 高级模式：多水印叠加")
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #0078d4;")
        page_layout.addWidget(header)

        hint = QLabel("最多支持 4 套水印同时生效（1 套主水印 + 3 套额外水印层）\n主水印在「水印设置」页配置，此页面管理额外水印层。")
        hint.setStyleSheet("color: #666; margin-bottom: 10px;")
        hint.setWordWrap(True)
        page_layout.addWidget(hint)

        self.extraWmTabs = QTabWidget()
        page_layout.addWidget(self.extraWmTabs)

        btn_layout = QHBoxLayout()
        self.btnAddWmLayer = QPushButton("➕ 添加水印层")
        self.btnAddWmLayer.clicked.connect(lambda: self._add_extra_watermark_tab())
        btn_layout.addWidget(self.btnAddWmLayer)
        btn_layout.addStretch()
        page_layout.addLayout(btn_layout)

        page_layout.addStretch()

        self.stackedWidget.addWidget(self.multi_wm_page)

        saved = self.app_config.load_extra_watermarks()
        for cfg in saved:
            self._add_extra_watermark_tab(cfg)

    def _add_extra_watermark_tab(self, cfg=None):
        """添加一个额外水印层 Tab"""
        if len(self._extra_wm_tabs) >= 3:
            QMessageBox.warning(self, "提示", "最多支持 3 个额外水印层（加上主水印共 4 套）")
            return

        if cfg is None:
            cfg = WatermarkConfig(text="", position="左下")

        idx = len(self._extra_wm_tabs) + 1
        tab = QWidget()
        form = QFormLayout(tab)

        cmb_type = QComboBox()
        cmb_type.addItems(["图片水印", "文字水印"])
        cmb_type.setCurrentIndex(0 if cfg.wm_type == "image" else 1)
        form.addRow("类型:", cmb_type)

        edt_content = QLineEdit()
        if cfg.wm_type == "image":
            edt_content.setText(cfg.image_path)
        else:
            edt_content.setText(cfg.text)
        edt_content.setPlaceholderText("文字内容 或 图片路径...")
        content_layout = QHBoxLayout()
        content_layout.addWidget(edt_content)
        btn_browse = QPushButton("浏览...")
        content_layout.addWidget(btn_browse)
        form.addRow("内容:", content_layout)

        # 浏览按钮事件
        def browse():
            if cmb_type.currentIndex() == 0:
                f, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "", "Images (*.png *.jpg *.bmp *.webp)")
                if f:
                    edt_content.setText(f)
        btn_browse.clicked.connect(browse)

        # 位置
        cmb_pos = QComboBox()
        cmb_pos.addItems(["左上", "右上", "左下", "右下", "上中", "下中", "居中"])
        cmb_pos.setCurrentText(cfg.position)
        form.addRow("位置:", cmb_pos)

        # 颜色
        btn_color = QPushButton(cfg.font_color or "#FFFFFF")
        btn_color.setFixedWidth(100)
        q_col = QColor(cfg.font_color or "#FFFFFF")
        btn_color.setStyleSheet(
            f"background-color: {q_col.name()}; color: {'black' if q_col.lightness() > 128 else 'white'}; border: 1px solid gray;"
        )
        def pick_color():
            color = QColorDialog.getColor(QColor(btn_color.text()), self, "选择颜色")
            if color.isValid():
                btn_color.setText(color.name().upper())
                btn_color.setStyleSheet(
                    f"background-color: {color.name()}; color: {'black' if color.lightness() > 128 else 'white'}; border: 1px solid gray;"
                )
        btn_color.clicked.connect(pick_color)
        form.addRow("文字颜色:", btn_color)

        # 不透明度
        spn_opacity = QDoubleSpinBox()
        spn_opacity.setRange(0.0, 1.0)
        spn_opacity.setSingleStep(0.1)
        spn_opacity.setValue(cfg.opacity)
        form.addRow("不透明度:", spn_opacity)

        # 缩放/字号
        spn_scale = QSpinBox()
        spn_scale.setRange(1, 100)
        spn_scale.setValue(cfg.text_size_pct if cfg.wm_type == "text" else cfg.image_scale_pct)
        form.addRow("缩放/字号(%):", spn_scale)

        # 智能选色
        chk_auto_color = QCheckBox("启用智能选色")
        chk_auto_color.setChecked(cfg.auto_color)
        chk_auto_color.setToolTip("自动分析视频画面，选择对比度最高的文字颜色")
        form.addRow("", chk_auto_color)

        # --- 背景颜色 ---
        chk_bg_enabled = QCheckBox("启用背景")
        chk_bg_enabled.setChecked(cfg.bg_enabled)
        chk_bg_enabled.setToolTip("为水印文字添加背景色块")
        btn_bg_color = QPushButton(cfg.bg_color or "#000000")
        btn_bg_color.setFixedWidth(100)
        bg_q_col = QColor(cfg.bg_color or "#000000")
        btn_bg_color.setStyleSheet(
            f"background-color: {bg_q_col.name()}; color: {'black' if bg_q_col.lightness() > 128 else 'white'}; border: 1px solid gray;"
        )
        def pick_bg_color(btn=btn_bg_color):
            color = QColorDialog.getColor(QColor(btn.text()), self, "选择背景颜色")
            if color.isValid():
                btn.setText(color.name().upper())
                btn.setStyleSheet(
                    f"background-color: {color.name()}; color: {'black' if color.lightness() > 128 else 'white'}; border: 1px solid gray;"
                )
        btn_bg_color.clicked.connect(pick_bg_color)
        bg_layout = QHBoxLayout()
        bg_layout.addWidget(chk_bg_enabled)
        bg_layout.addWidget(btn_bg_color)
        bg_layout.addStretch()
        form.addRow("背景颜色:", bg_layout)

        # --- 居中垂直偏移 ---
        spn_center_y_offset = QSpinBox()
        spn_center_y_offset.setRange(-2000, 2000)
        spn_center_y_offset.setSingleStep(10)
        spn_center_y_offset.setValue(cfg.center_y_offset)
        spn_center_y_offset.setToolTip("居中位置时的垂直偏移量（正值下移，负值上移）")
        spn_center_y_offset.setSuffix(" px")
        form.addRow("居中Y偏移:", spn_center_y_offset)

        # 边距
        spn_margin = QSpinBox()
        spn_margin.setRange(0, 500)
        spn_margin.setValue(cfg.margin)
        form.addRow("边距:", spn_margin)

        # 删除按钮
        btn_delete = QPushButton("🗑️ 删除该水印层")
        btn_delete.setStyleSheet("color: red;")
        form.addRow("", btn_delete)

        # 保存控件引用
        tab_data = {
            "widget": tab,
            "cmb_type": cmb_type,
            "edt_content": edt_content,
            "cmb_pos": cmb_pos,
            "btn_color": btn_color,
            "spn_opacity": spn_opacity,
            "spn_scale": spn_scale,
            "spn_margin": spn_margin,
            "chk_auto_color": chk_auto_color,
            "chk_bg_enabled": chk_bg_enabled,
            "btn_bg_color": btn_bg_color,
            "spn_center_y_offset": spn_center_y_offset,
        }
        self._extra_wm_tabs.append(tab_data)
        self.extraWmTabs.addTab(tab, f"水印层 {idx}")

        # 删除按钮绑定
        btn_delete.clicked.connect(lambda: self._remove_extra_watermark_tab(tab_data))

        # 更新添加按钮状态
        if len(self._extra_wm_tabs) >= 3:
            self.btnAddWmLayer.setEnabled(False)

    def _remove_extra_watermark_tab(self, tab_data):
        """删除一个额外水印层 Tab"""
        if tab_data in self._extra_wm_tabs:
            idx = self.extraWmTabs.indexOf(tab_data["widget"])
            if idx >= 0:
                self.extraWmTabs.removeTab(idx)
            self._extra_wm_tabs.remove(tab_data)
            # 重新编号
            for i, td in enumerate(self._extra_wm_tabs):
                self.extraWmTabs.setTabText(i, f"水印层 {i + 1}")
            # 恢复添加按钮
            self.btnAddWmLayer.setEnabled(True)

    def get_extra_watermarks(self):
        """收集所有额外水印层的配置，返回 WatermarkConfig 列表"""
        result = []
        for td in self._extra_wm_tabs:
            cfg = WatermarkConfig()
            is_image = (td["cmb_type"].currentIndex() == 0)
            cfg.wm_type = "image" if is_image else "text"
            if is_image:
                cfg.image_path = td["edt_content"].text()
            else:
                cfg.text = td["edt_content"].text()
            cfg.position = td["cmb_pos"].currentText()
            cfg.font_color = td["btn_color"].text()
            cfg.opacity = td["spn_opacity"].value()
            if is_image:
                cfg.image_scale_pct = td["spn_scale"].value()
            else:
                cfg.text_size_pct = td["spn_scale"].value()
            cfg.margin = td["spn_margin"].value()
            cfg.auto_color = td["chk_auto_color"].isChecked()
            # 背景色
            cfg.bg_enabled = td["chk_bg_enabled"].isChecked()
            cfg.bg_color = td["btn_bg_color"].text()
            # 居中Y偏移
            cfg.center_y_offset = td["spn_center_y_offset"].value()
            result.append(cfg)
        return result

    def accept(self):
        # 1. 获取当前最新设置
        new_cfg = self.get_config()
        
        # 2. 保存到“最近配置”
        self.app_config.save_last_config(new_cfg)
        
        # 3. 核心修复：如果当前选中了某个模板，同步更新它
        current_template_index = self.cmbTemplates.currentIndex()
        if current_template_index > 0:
            template_name = self.cmbTemplates.itemText(current_template_index)
            self.app_config.save_template(template_name, new_cfg)
            self.app_config.set_last_template_name(template_name)
        else:
            self.app_config.set_last_template_name("")
            
        super().accept()

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.edtOutDir.setText(d)
            self.chkSameDir.setChecked(False)

    def _browse_wm(self):
        if self.cmbType.currentIndex() == 0: # Image
            f, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "", "Images (*.png *.jpg *.bmp *.webp)")
            if f:
                self.edtWmContent.setText(f)
                self._set_builtin_from_path(f)
        else:
            # Text mode browse usually for font, but here content is text. 
            # If user wants to browse font, we added that in plan but UI simplified here.
            # Assuming simple text input for now.
            pass

    def _toggle_out_dir(self):
        is_inplace = self.chkInplace.isChecked()
        # 如果原地替换开启，输出目录设置变为不相关
        if is_inplace:
            self.chkSameDir.setEnabled(False)
            self.edtOutDir.setEnabled(False)
            self.btnBrowseOut.setEnabled(False)
        else:
            self.chkSameDir.setEnabled(True)
            enabled = not self.chkSameDir.isChecked()
            self.edtOutDir.setEnabled(enabled)
            self.btnBrowseOut.setEnabled(enabled)
        self._emit_config()

    def _toggle_wm_type(self):
        is_image = (self.cmbType.currentIndex() == 0)
        self.btnBrowseWm.setVisible(is_image)
        # 内置标识始终可见，方便快速选预设
        self.label_builtin.setVisible(True)
        self.cmbBuiltin.setVisible(True)
        
        self.label_content.setText("图片路径" if is_image else "文字内容")
        self.label_scale.setText("图片缩放 (%)" if is_image else "字体大小 (%)")
        self.spnScale.setValue(100 if is_image else 2)

        if is_image:
            self.edtWmContent.setText("")

        # 羽化仅限图片
        self.label_feather.setVisible(is_image)
        self.spnFeather.setVisible(is_image)
        # 字体仅限文字
        self.btnSelectFont.setVisible(not is_image)
        # 颜色仅限文字
        self.label_color.setVisible(not is_image)
        self.btnSelectColor.setVisible(not is_image)
        self.chkAutoColor.setVisible(not is_image)
        # 背景色仅限文字
        self.label_bg_color.setVisible(not is_image)
        self.chkBgEnabled.setVisible(not is_image)
        self.btnSelectBgColor.setVisible(not is_image)
        # 居中Y偏移对图片和文字水印都生效，始终可见
        self.label_center_y_offset.setVisible(True)
        self.spnCenterYOffset.setVisible(True)

    def _select_color(self):
        color = QColorDialog.getColor(QColor(self.btnSelectColor.text()), self, "选择水印颜色")
        if color.isValid():
            hex_color = color.name().upper()
            self.btnSelectColor.setText(hex_color)
            self.btnSelectColor.setStyleSheet(f"background-color: {hex_color}; color: {'black' if color.lightness() > 128 else 'white'}; border: 1px solid gray;")
            self._emit_config()

    def _select_bg_color(self):
        """选择水印背景颜色"""
        color = QColorDialog.getColor(QColor(self.btnSelectBgColor.text()), self, "选择背景颜色")
        if color.isValid():
            hex_color = color.name().upper()
            self.btnSelectBgColor.setText(hex_color)
            self.btnSelectBgColor.setStyleSheet(f"background-color: {hex_color}; color: {'black' if color.lightness() > 128 else 'white'}; border: 1px solid gray;")
            self._emit_config()

    def _get_builtin_map(self):
        # 基于当前文件找到 resources 目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res_dir = os.path.join(base_dir, "resources", "watermarks")
        return {
            1: os.path.join(res_dir, "gen_de_ai.png"),
            2: os.path.join(res_dir, "imagine_create_de_ai.png"),
            3: os.path.join(res_dir, "gen_cu_ai.png"),
            4: os.path.join(res_dir, "background_water.png"),
        }

    def _on_builtin_changed(self, index):
        if index == 0: # 自定义图片
            return
        
        # 模式切换映射：1 是图片，2/3 改为文字模式（因为生成图配额限制且文字更清晰/单行）
        if index == 1:
            self.cmbType.setCurrentIndex(0) # 图片水印
            builtin_map = self._get_builtin_map()
            path = builtin_map.get(index)
            if path and os.path.exists(path):
                self.edtWmContent.setText(path)
        else:
            self.cmbType.setCurrentIndex(1) # 文字水印
            texts = {
                2: "Imagine create de AI",
                3: "Generat cu AI"
            }
            self.edtWmContent.setText(texts.get(index, ""))
            # 自动设置一些好看的默认值（如果需要）
            self.spnOpacity.setValue(0.7)

    def _save_template(self):
        name, ok = QInputDialog.getText(self, "保存模板", "模板名称:")
        if ok and name:
            if name == "-- 选择模板 --":
                QMessageBox.warning(self, "错误", "不允许使用的名称")
                return
            cfg = self.get_config()
            self.app_config.save_template(name, cfg)
            self._refresh_templates()
            self.cmbTemplates.setCurrentText(name)
            QMessageBox.information(self, "提示", f"模板 '{name}' 已保存")

    def _delete_template(self):
        name = self.cmbTemplates.currentText()
        if self.cmbTemplates.currentIndex() <= 0:
            return
        
        ret = QMessageBox.question(self, "确认", f"确定要删除模板 '{name}' 吗？")
        if ret == QMessageBox.Yes:
            self.app_config.delete_template(name)
            self._refresh_templates()

    def _on_template_selected(self, index):
        if index <= 0:
            return
        
        name = self.cmbTemplates.currentText()
        templates = self.app_config.get_templates()
        if name in templates:
            data = templates[name]
            # 兼容性处理：从字典中还原配置对象
            cfg = WatermarkConfig.from_dict(data)
            
            # 记录当前非模板相关的本地路径设置
            old_out_dir = self.edtOutDir.text()
            old_same_dir = self.chkSameDir.isChecked()
            
            # 使用状态保护模式
            was_loading = self._is_loading
            self._is_loading = True
            try:
                # 执行加载
                self._load_from_config(cfg)
                
                # 还原不应被模板覆盖的本地路径/状态
                self.edtOutDir.setText(old_out_dir)
                self.chkSameDir.setChecked(old_same_dir)
                
                # 确保 UI 联动状态正确
                self._toggle_out_dir()
                self._toggle_wm_type()
                
                # 手动触发信号
                self._emit_config()
            finally:
                self._is_loading = was_loading

    def _set_builtin_from_path(self, path):
        builtin_map = self._get_builtin_map()
        # 反向查找
        for idx, p in builtin_map.items():
            if os.path.abspath(path) == os.path.abspath(p):
                self.cmbBuiltin.setCurrentIndex(idx)
                return
        self.cmbBuiltin.setCurrentIndex(0)

    def _select_font(self):
        # 尝试创建一个 QFont 对象
        current_font = QFont()
        if self.current_cfg.font_name:
            current_font.setFamily(self.current_cfg.font_name)
            
        ok, font = QFontDialog.getFont(current_font, self, "选择水印字体")
        if ok:
            # 在 Windows 等平台上获取字体文件的绝对路径
            # 注意：PySide 本身不直接提供字体文件路径，需要一些技巧或库
            # 简单起见，我们保存 family 并在 common 里寻找匹配
            self.current_cfg.font_name = font.family()
            # 尝试通过 QFontInfo 寻找更准确的家族名
            info = QFontInfo(font)
            family = info.family()
            self.current_cfg.font_name = family
            
            self.btnSelectFont.setText(f"字体: {family}")
            
            # 触发一次实时预览发送
            self._emit_config()
