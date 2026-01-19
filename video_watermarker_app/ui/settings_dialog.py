#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from video_watermarker_app.ui.ui_settings_dialog import Ui_SettingsDialog
from video_watermarker_app.utils.config import AppConfig, WatermarkConfig
from video_watermarker_app.utils.common import get_available_encoders
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QListWidgetItem, QFontDialog, QMessageBox, 
    QInputDialog, QLabel, QPushButton, QCheckBox, QHBoxLayout, QColorDialog
)
from PySide6.QtGui import QColor, QFont, QFontInfo
from PySide6.QtCore import Signal


class SettingsDialog(QDialog, Ui_SettingsDialog):

    config_changed = Signal(WatermarkConfig)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        
        self.app_config = AppConfig()
        self._is_loading = True

        self.label_color = QLabel("文字颜色")
        self.btnSelectColor = QPushButton("#FFFFFF")
        self.btnSelectColor.setFixedWidth(100)
        self.chkAutoColor = QCheckBox("智能选色")
        self.chkAutoColor.setToolTip("取第5帧画面计算补色，自动调整文字颜色与描边")
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(self.btnSelectColor)
        color_layout.addWidget(self.chkAutoColor)
        color_layout.addStretch()
        self.formLayoutWm.insertRow(3, self.label_color, color_layout)

        self.btnSelectColor.clicked.connect(self._select_color)
        self.chkAutoColor.stateChanged.connect(self._emit_config)

        self.chkInplace = QCheckBox("处理后原地替换原文件 (慎用)")
        self.chkInplace.setToolTip("开启后将覆盖原始视频/图片，建议开启前确认设置无误")
        self.formLayoutBasic.insertRow(2, "", self.chkInplace)

        self.current_cfg = self.app_config.load_last_config()

        self._load_from_config(self.current_cfg)

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

        for widget in [self.cmbType, self.cmbPosition, self.cmbPreset, self.cmbExt, self.cmbBuiltin]:
             widget.currentIndexChanged.connect(self._emit_config)
        for widget in [self.spnOpacity, self.spnScale, self.spnMargin, self.spnCrf, self.spnFeather, self.spnConcurrent]:
             widget.valueChanged.connect(self._emit_config)
        self.chkGpu.stateChanged.connect(self._emit_config)
        self.edtWmContent.textChanged.connect(self._on_content_changed)
        self.btnSelectFont.clicked.connect(self._select_font)
        
        self._check_gpu_support()
        self._refresh_templates()

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

    def _load_from_config(self, cfg: WatermarkConfig):
        was_loading = self._is_loading
        self._is_loading = True
        # 暂时阻塞所有重要控件的信号，防止配置加载时的中间态触发不完整的 sync/update
        widgets_to_block = [
            self.cmbType, self.cmbPosition, self.cmbPreset, self.cmbExt, self.cmbBuiltin,
            self.spnOpacity, self.spnScale, self.spnMargin, self.spnCrf, self.spnFeather,
            self.spnConcurrent, self.chkGpu, self.chkSameDir, self.chkAutoColor, self.chkInplace
        ]
        for w in widgets_to_block: w.blockSignals(True)
        
        try:
            self.current_cfg = cfg
            self.edtOutDir.setText(cfg.output_dir)
            self.chkSameDir.setChecked(cfg.same_dir)
            self.chkInplace.setChecked(cfg.inplace_replace)

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

            self.spnCrf.setValue(cfg.crf)
            self.cmbPreset.setCurrentText(cfg.preset)
            self.cmbExt.setCurrentText(cfg.out_ext)
            self.chkGpu.setChecked(cfg.gpu_enabled)
            self.spnConcurrent.setValue(cfg.max_concurrent)
        finally:
            for w in widgets_to_block: w.blockSignals(False)
            self.edtWmContent.blockSignals(False)

        self._toggle_out_dir()
        self._toggle_wm_type()

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

        cfg.custom_x = self.current_cfg.custom_x
        cfg.custom_y = self.current_cfg.custom_y

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

    def accept(self):
        new_cfg = self.get_config()
        self.app_config.save_last_config(new_cfg)
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
            pass

    def _toggle_out_dir(self):
        is_inplace = self.chkInplace.isChecked()
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
        self.label_builtin.setVisible(True)
        self.cmbBuiltin.setVisible(True)
        
        self.label_content.setText("图片路径" if is_image else "文字内容")
        self.label_scale.setText("图片缩放 (%)" if is_image else "字体大小 (%)")
        self.label_feather.setVisible(is_image)
        self.spnFeather.setVisible(is_image)
        self.btnSelectFont.setVisible(not is_image)
        self.label_color.setVisible(not is_image)
        self.btnSelectColor.setVisible(not is_image)
        self.chkAutoColor.setVisible(not is_image)

    def _select_color(self):
        color = QColorDialog.getColor(QColor(self.btnSelectColor.text()), self, "选择水印颜色")
        if color.isValid():
            hex_color = color.name().upper()
            self.btnSelectColor.setText(hex_color)
            self.btnSelectColor.setStyleSheet(f"background-color: {hex_color}; color: {'black' if color.lightness() > 128 else 'white'}; border: 1px solid gray;")
            self._emit_config()

    def _get_builtin_map(self):
        # 基于当前文件找到 resources 目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res_dir = os.path.join(base_dir, "resources", "watermarks")
        return {
            1: os.path.join(res_dir, "gen_de_ai.png"),
            2: os.path.join(res_dir, "imagine_create_de_ai.png"),
            3: os.path.join(res_dir, "gen_cu_ai.png"),
        }

    def _on_builtin_changed(self, index):
        if index == 0:
            return

        if index == 1:
            self.cmbType.setCurrentIndex(0)
            builtin_map = self._get_builtin_map()
            path = builtin_map.get(index)
            if path and os.path.exists(path):
                self.edtWmContent.setText(path)
        else:
            self.cmbType.setCurrentIndex(1)
            texts = {
                2: "Imagine create de AI",
                3: "Generat cu AI"
            }
            self.edtWmContent.setText(texts.get(index, ""))
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
            cfg = WatermarkConfig.from_dict(data)

            old_out_dir = self.edtOutDir.text()
            old_same_dir = self.chkSameDir.isChecked()

            was_loading = self._is_loading
            self._is_loading = True
            try:
                self._load_from_config(cfg)
                self.edtOutDir.setText(old_out_dir)
                self.chkSameDir.setChecked(old_same_dir)
                self._toggle_out_dir()
                self._toggle_wm_type()
                self._emit_config()
            finally:
                self._is_loading = was_loading

    def _set_builtin_from_path(self, path):
        builtin_map = self._get_builtin_map()
        for idx, p in builtin_map.items():
            if os.path.abspath(path) == os.path.abspath(p):
                self.cmbBuiltin.setCurrentIndex(idx)
                return
        self.cmbBuiltin.setCurrentIndex(0)

    def _select_font(self):
        current_font = QFont()
        if self.current_cfg.font_name:
            current_font.setFamily(self.current_cfg.font_name)
            
        ok, font = QFontDialog.getFont(current_font, self, "选择水印字体")
        if ok:
            self.current_cfg.font_name = font.family()
            info = QFontInfo(font)
            family = info.family()
            self.current_cfg.font_name = family
            self.btnSelectFont.setText(f"字体: {family}")
            self._emit_config()
