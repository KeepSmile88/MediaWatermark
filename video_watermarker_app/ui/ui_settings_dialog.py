# -*- coding: utf-8 -*-

from PySide6.QtCore import (QCoreApplication, QMetaObject, QRect, QSize, Qt)
from PySide6.QtGui import (QStandardItemModel, QStandardItem)
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget
)

class Ui_SettingsDialog(object):
    def setupUi(self, SettingsDialog):
        if not SettingsDialog.objectName():
            SettingsDialog.setObjectName(u"SettingsDialog")
        SettingsDialog.resize(700, 500)
        
        self.horizontalLayout = QHBoxLayout(SettingsDialog)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        
        self.listNav = QListWidget(SettingsDialog)
        QListWidgetItem(self.listNav)
        QListWidgetItem(self.listNav)
        QListWidgetItem(self.listNav)
        self.listNav.setObjectName(u"listNav")
        self.listNav.setMaximumSize(QSize(150, 16777215))
        self.horizontalLayout.addWidget(self.listNav)
        
        self.rightLayout = QVBoxLayout()
        self.rightLayout.setObjectName(u"rightLayout")
        
        self.stackedWidget = QStackedWidget(SettingsDialog)
        self.stackedWidget.setObjectName(u"stackedWidget")
        
        # Page 1: Basic
        self.pageBasic = QWidget()
        self.pageBasic.setObjectName(u"pageBasic")
        self.formLayoutBasic = QFormLayout(self.pageBasic)
        self.formLayoutBasic.setObjectName(u"formLayoutBasic")
        
        self.label_1 = QLabel(self.pageBasic)
        self.label_1.setObjectName(u"label_1")
        self.formLayoutBasic.setWidget(0, QFormLayout.LabelRole, self.label_1)
        
        self.hLayoutOutDir = QHBoxLayout()
        self.hLayoutOutDir.setObjectName(u"hLayoutOutDir")
        self.edtOutDir = QLineEdit(self.pageBasic)
        self.edtOutDir.setObjectName(u"edtOutDir")
        self.edtOutDir.setReadOnly(True)
        self.hLayoutOutDir.addWidget(self.edtOutDir)
        self.btnBrowseOut = QPushButton(self.pageBasic)
        self.btnBrowseOut.setObjectName(u"btnBrowseOut")
        self.hLayoutOutDir.addWidget(self.btnBrowseOut)
        self.formLayoutBasic.setLayout(0, QFormLayout.FieldRole, self.hLayoutOutDir)
        
        self.chkSameDir = QCheckBox(self.pageBasic)
        self.chkSameDir.setObjectName(u"chkSameDir")
        self.chkSameDir.setChecked(True)
        self.formLayoutBasic.setWidget(1, QFormLayout.FieldRole, self.chkSameDir)
        
        # 模板管理区域
        self.line_template = QFrame(self.pageBasic)
        self.line_template.setFrameShape(QFrame.HLine)
        self.formLayoutBasic.setWidget(2, QFormLayout.SpanningRole, self.line_template)

        self.label_template = QLabel(self.pageBasic)
        self.label_template.setObjectName(u"label_template")
        self.formLayoutBasic.setWidget(3, QFormLayout.LabelRole, self.label_template)

        self.hLayoutTemplates = QHBoxLayout()
        self.hLayoutTemplates.setObjectName(u"hLayoutTemplates")
        self.cmbTemplates = QComboBox(self.pageBasic)
        self.cmbTemplates.setObjectName(u"cmbTemplates")
        self.hLayoutTemplates.addWidget(self.cmbTemplates, 1)
        self.btnSaveTemplate = QPushButton(self.pageBasic)
        self.btnSaveTemplate.setObjectName(u"btnSaveTemplate")
        self.hLayoutTemplates.addWidget(self.btnSaveTemplate)
        self.btnDelTemplate = QPushButton(self.pageBasic)
        self.btnDelTemplate.setObjectName(u"btnDelTemplate")
        self.hLayoutTemplates.addWidget(self.btnDelTemplate)
        self.formLayoutBasic.setLayout(3, QFormLayout.FieldRole, self.hLayoutTemplates)
        
        self.stackedWidget.addWidget(self.pageBasic)
        
        # Page 2: Watermark
        self.pageWatermark = QWidget()
        self.pageWatermark.setObjectName(u"pageWatermark")
        self.formLayoutWm = QFormLayout(self.pageWatermark)
        self.formLayoutWm.setObjectName(u"formLayoutWm")
        
        self.label_type = QLabel(self.pageWatermark)
        self.label_type.setObjectName(u"label_type")
        self.formLayoutWm.setWidget(0, QFormLayout.LabelRole, self.label_type)
        
        self.cmbType = QComboBox(self.pageWatermark)
        self.cmbType.addItem("")
        self.cmbType.addItem("")
        self.cmbType.setObjectName(u"cmbType")
        self.formLayoutWm.setWidget(0, QFormLayout.FieldRole, self.cmbType)

        self.label_builtin = QLabel(self.pageWatermark)
        self.label_builtin.setObjectName(u"label_builtin")
        self.formLayoutWm.setWidget(1, QFormLayout.LabelRole, self.label_builtin)

        self.cmbBuiltin = QComboBox(self.pageWatermark)
        self.cmbBuiltin.setObjectName(u"cmbBuiltin")
        self.cmbBuiltin.addItem(u"自定义图片")
        self.cmbBuiltin.addItem(u"Generat de AI")
        self.cmbBuiltin.addItem(u"Imagine create de AI")
        self.cmbBuiltin.addItem(u"Generat cu AI")
        self.formLayoutWm.setWidget(1, QFormLayout.FieldRole, self.cmbBuiltin)
        
        self.label_content = QLabel(self.pageWatermark)
        self.label_content.setObjectName(u"label_content")
        self.formLayoutWm.setWidget(2, QFormLayout.LabelRole, self.label_content)
        
        self.hLayoutWmContent = QHBoxLayout()
        self.hLayoutWmContent.setObjectName(u"hLayoutWmContent")
        self.edtWmContent = QLineEdit(self.pageWatermark)
        self.edtWmContent.setObjectName(u"edtWmContent")
        self.hLayoutWmContent.addWidget(self.edtWmContent)
        self.btnBrowseWm = QPushButton(self.pageWatermark)
        self.btnBrowseWm.setObjectName(u"btnBrowseWm")
        self.hLayoutWmContent.addWidget(self.btnBrowseWm)
        self.formLayoutWm.setLayout(2, QFormLayout.FieldRole, self.hLayoutWmContent)
        
        self.label_pos = QLabel(self.pageWatermark)
        self.label_pos.setObjectName(u"label_pos")
        self.formLayoutWm.setWidget(3, QFormLayout.LabelRole, self.label_pos)
        
        self.cmbPosition = QComboBox(self.pageWatermark)
        self.cmbPosition.addItems(["右下", "左下", "右上", "左上", "居中", "自定义"])
        self.cmbPosition.setObjectName(u"cmbPosition")
        self.formLayoutWm.setWidget(3, QFormLayout.FieldRole, self.cmbPosition)
        
        self.label_opacity = QLabel(self.pageWatermark)
        self.label_opacity.setObjectName(u"label_opacity")
        self.formLayoutWm.setWidget(4, QFormLayout.LabelRole, self.label_opacity)
        
        self.spnOpacity = QDoubleSpinBox(self.pageWatermark)
        self.spnOpacity.setObjectName(u"spnOpacity")
        self.spnOpacity.setMaximum(1.0)
        self.spnOpacity.setSingleStep(0.1)
        self.spnOpacity.setValue(0.8)
        self.formLayoutWm.setWidget(4, QFormLayout.FieldRole, self.spnOpacity)
        
        self.label_scale = QLabel(self.pageWatermark)
        self.label_scale.setObjectName(u"label_scale")
        self.formLayoutWm.setWidget(5, QFormLayout.LabelRole, self.label_scale)
        
        self.spnScale = QSpinBox(self.pageWatermark)
        self.spnScale.setObjectName(u"spnScale")
        self.spnScale.setMinimum(1)
        self.spnScale.setMaximum(100)
        self.spnScale.setValue(15)
        self.formLayoutWm.setWidget(5, QFormLayout.FieldRole, self.spnScale)
        
        self.label_margin = QLabel(self.pageWatermark)
        self.label_margin.setObjectName(u"label_margin")
        self.formLayoutWm.setWidget(6, QFormLayout.LabelRole, self.label_margin)

        self.spnMargin = QSpinBox(self.pageWatermark)
        self.spnMargin.setObjectName(u"spnMargin")
        self.spnMargin.setMaximum(1000)
        self.spnMargin.setValue(20)
        self.formLayoutWm.setWidget(6, QFormLayout.FieldRole, self.spnMargin)

        self.label_feather = QLabel(self.pageWatermark)
        self.label_feather.setObjectName(u"label_feather")
        self.formLayoutWm.setWidget(7, QFormLayout.LabelRole, self.label_feather)

        self.spnFeather = QSpinBox(self.pageWatermark)
        self.spnFeather.setObjectName(u"spnFeather")
        self.spnFeather.setMaximum(20)
        self.spnFeather.setValue(0)
        self.formLayoutWm.setWidget(7, QFormLayout.FieldRole, self.spnFeather)

        self.btnSelectFont = QPushButton(self.pageWatermark)
        self.btnSelectFont.setObjectName(u"btnSelectFont")
        self.formLayoutWm.setWidget(8, QFormLayout.FieldRole, self.btnSelectFont)
        
        self.stackedWidget.addWidget(self.pageWatermark)
        
        # Page 3: Output
        self.pageOutput = QWidget()
        self.pageOutput.setObjectName(u"pageOutput")
        self.formLayoutOut = QFormLayout(self.pageOutput)
        self.formLayoutOut.setObjectName(u"formLayoutOut")
        
        self.label_crf = QLabel(self.pageOutput)
        self.label_crf.setObjectName(u"label_crf")
        self.formLayoutOut.setWidget(0, QFormLayout.LabelRole, self.label_crf)
        
        self.spnCrf = QSpinBox(self.pageOutput)
        self.spnCrf.setObjectName(u"spnCrf")
        self.spnCrf.setMaximum(51)
        self.spnCrf.setValue(23)
        self.formLayoutOut.setWidget(0, QFormLayout.FieldRole, self.spnCrf)
        
        self.label_preset = QLabel(self.pageOutput)
        self.label_preset.setObjectName(u"label_preset")
        self.formLayoutOut.setWidget(1, QFormLayout.LabelRole, self.label_preset)
        
        self.cmbPreset = QComboBox(self.pageOutput)
        self.cmbPreset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.cmbPreset.setObjectName(u"cmbPreset")
        self.formLayoutOut.setWidget(1, QFormLayout.FieldRole, self.cmbPreset)
        
        self.label_ext = QLabel(self.pageOutput)
        self.label_ext.setObjectName(u"label_ext")
        self.formLayoutOut.setWidget(2, QFormLayout.LabelRole, self.label_ext)
        
        self.cmbExt = QComboBox(self.pageOutput)
        self.cmbExt.addItems(["mp4", "mkv", "mov", "avi", "webm"])
        self.cmbExt.setObjectName(u"cmbExt")
        self.formLayoutOut.setWidget(2, QFormLayout.FieldRole, self.cmbExt)
        
        self.line_gpu = QFrame(self.pageOutput)
        self.line_gpu.setFrameShape(QFrame.HLine)
        self.formLayoutOut.setWidget(3, QFormLayout.SpanningRole, self.line_gpu)

        self.chkGpu = QCheckBox(self.pageOutput)
        self.chkGpu.setObjectName(u"chkGpu")
        self.formLayoutOut.setWidget(4, QFormLayout.FieldRole, self.chkGpu)

        self.label_concurrent = QLabel(self.pageOutput)
        self.label_concurrent.setObjectName(u"label_concurrent")
        self.formLayoutOut.setWidget(5, QFormLayout.LabelRole, self.label_concurrent)

        self.spnConcurrent = QSpinBox(self.pageOutput)
        self.spnConcurrent.setObjectName(u"spnConcurrent")
        self.spnConcurrent.setMinimum(1)
        self.spnConcurrent.setMaximum(4)
        self.spnConcurrent.setValue(1)
        self.formLayoutOut.setWidget(5, QFormLayout.FieldRole, self.spnConcurrent)
        
        self.stackedWidget.addWidget(self.pageOutput)
        
        self.rightLayout.addWidget(self.stackedWidget)
        
        self.buttonBox = QDialogButtonBox(SettingsDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)
        self.rightLayout.addWidget(self.buttonBox)
        
        self.horizontalLayout.addLayout(self.rightLayout)

        self.retranslateUi(SettingsDialog)
        self.stackedWidget.setCurrentIndex(0)
        self.buttonBox.accepted.connect(SettingsDialog.accept)
        self.buttonBox.rejected.connect(SettingsDialog.reject)
        QMetaObject.connectSlotsByName(SettingsDialog)
    # setupUi

    def retranslateUi(self, SettingsDialog):
        SettingsDialog.setWindowTitle(QCoreApplication.translate("SettingsDialog", u"\u8bbe\u7f6e", None))

        __sortingEnabled = self.listNav.isSortingEnabled()
        self.listNav.setSortingEnabled(False)
        ___qlistwidgetitem = self.listNav.item(0)
        ___qlistwidgetitem.setText(QCoreApplication.translate("SettingsDialog", u"\u57fa\u672c\u8bbe\u7f6e", None));
        ___qlistwidgetitem1 = self.listNav.item(1)
        ___qlistwidgetitem1.setText(QCoreApplication.translate("SettingsDialog", u"\u6c34\u5370\u8bbe\u7f6e", None));
        ___qlistwidgetitem2 = self.listNav.item(2)
        ___qlistwidgetitem2.setText(QCoreApplication.translate("SettingsDialog", u"\u8f93\u51fa\u8bbe\u7f6e", None));
        self.listNav.setSortingEnabled(__sortingEnabled)

        self.label_1.setText(QCoreApplication.translate("SettingsDialog", u"\u8f93\u51fa\u76ee\u5f55", None))
        self.btnBrowseOut.setText(QCoreApplication.translate("SettingsDialog", u"\u6d4f\u89c8...", None))
        self.chkSameDir.setText(QCoreApplication.translate("SettingsDialog", u"\u8f93\u51fa\u5230\u6e90\u6587\u4ef6\u540c\u76ee\u5f55", None))
        self.label_template.setText(QCoreApplication.translate("SettingsDialog", u"\u914d\u7f6e\u6a21\u677f", None))
        self.btnSaveTemplate.setText(QCoreApplication.translate("SettingsDialog", u"\u4fdd\u5b58\u5f53\u524d...", None))
        self.btnDelTemplate.setText(QCoreApplication.translate("SettingsDialog", u"\u5220\u9664", None))
        self.label_type.setText(QCoreApplication.translate("SettingsDialog", u"\u6c34\u5370\u7c7b\u578b", None))
        self.cmbType.setItemText(0, QCoreApplication.translate("SettingsDialog", u"\u56fe\u7247\u6c34\u5370", None))
        self.cmbType.setItemText(1, QCoreApplication.translate("SettingsDialog", u"\u6587\u5b57\u6c34\u5370", None))
        self.label_builtin.setText(QCoreApplication.translate("SettingsDialog", u"\u5185\u7f6e\u6807\u8bc6", None))
        self.label_content.setText(QCoreApplication.translate("SettingsDialog", u"\u5185\u5bb9/\u8def\u5f84", None))
        self.btnBrowseWm.setText(QCoreApplication.translate("SettingsDialog", u"\u9009\u62e9\u56fe\u7247...", None))
        self.label_pos.setText(QCoreApplication.translate("SettingsDialog", u"\u4f4d\u7f6e", None))
        self.label_opacity.setText(QCoreApplication.translate("SettingsDialog", u"\u900f\u660e\u5ea6 (0-1)", None))
        self.label_scale.setText(QCoreApplication.translate("SettingsDialog", u"\u7f29\u653e/\u5927\u5c0f (%)", None))
        self.label_margin.setText(QCoreApplication.translate("SettingsDialog", u"\u8fb9\u8ddd (px)", None))
        self.label_feather.setText(QCoreApplication.translate("SettingsDialog", u"\u7fbd\u5316\u534a\u5f84 (px)", None))
        self.btnSelectFont.setText(QCoreApplication.translate("SettingsDialog", u"\u9009\u62e9\u5b57\u4f53...", None))
        self.label_crf.setText(QCoreApplication.translate("SettingsDialog", u"\u89c6\u9891\u8d28\u91cf (CRF)", None))
        self.label_preset.setText(QCoreApplication.translate("SettingsDialog", u"\u7f16\u7801\u901f\u5ea6 (Preset)", None))
        self.label_ext.setText(QCoreApplication.translate("SettingsDialog", u"\u8f93\u51fa\u683c\u5f0f", None))
        self.chkGpu.setText(QCoreApplication.translate("SettingsDialog", u"\u5f00\u542f GPU \u786c\u4ef6\u52a0\u901f (NVENC/QSV/AMF)", None))
        self.label_concurrent.setText(QCoreApplication.translate("SettingsDialog", u"\u5e76\u53d1\u4efb\u52a1\u6570", None))
    # retranslateUi
