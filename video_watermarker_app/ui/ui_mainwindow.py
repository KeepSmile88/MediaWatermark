# -*- coding: utf-8 -*-

from PySide6.QtCore import (QCoreApplication, QMetaObject, QRect, QSize, Qt)
from PySide6.QtGui import (QAction, QIcon, QFont)
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMenu,
    QMenuBar, QProgressBar, QPushButton, QSizePolicy, QSpacerItem,
    QStatusBar, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QFrame, QGridLayout, QGroupBox, QAbstractItemView
)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1100, 700)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        
        # Main Horizontal Layout (Split View)
        self.mainLayout = QHBoxLayout(self.centralwidget)
        self.mainLayout.setSpacing(0)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        
        # --- Left Panel: Watermark Settings ---
        self.leftPanel = QWidget(self.centralwidget)
        self.leftPanel.setObjectName(u"leftPanel")
        self.leftPanel.setMinimumWidth(300)
        self.leftPanel.setMaximumWidth(350)
        
        self.leftLayout = QVBoxLayout(self.leftPanel)
        self.leftLayout.setSpacing(20)
        self.leftLayout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        self.lblLeftTitle = QLabel(self.leftPanel)
        self.lblLeftTitle.setObjectName(u"lblLeftTitle")
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPointSize(12)
        self.lblLeftTitle.setFont(font_title)
        self.leftLayout.addWidget(self.lblLeftTitle)
        
        # Preview Area
        self.lblPreviewTitle = QLabel(self.leftPanel)
        self.lblPreviewTitle.setObjectName(u"lblPreviewTitle")
        self.leftLayout.addWidget(self.lblPreviewTitle)

        self.previewContainer = QFrame(self.leftPanel)
        self.previewContainer.setObjectName(u"previewContainer")
        self.previewContainer.setFrameShape(QFrame.StyledPanel)
        self.previewContainer.setFrameShadow(QFrame.Raised)
        self.previewContainer.setMinimumHeight(150)
        
        self.previewLayout = QVBoxLayout(self.previewContainer)
        self.previewLayout.setContentsMargins(0,0,0,0)
        
        self.lblWatermarkPreview = QLabel(self.previewContainer)
        self.lblWatermarkPreview.setObjectName(u"lblWatermarkPreview")
        self.lblWatermarkPreview.setAlignment(Qt.AlignCenter)
        self.lblWatermarkPreview.setText(u"AI Generated") # Placeholder
        self.lblWatermarkPreview.setStyleSheet("background-color: #1a1a1a; color: white; border-radius: 8px;")
        self.previewLayout.addWidget(self.lblWatermarkPreview)
        
        self.leftLayout.addWidget(self.previewContainer)
        
        # Actions
        self.btnClearWatermark = QPushButton(self.leftPanel)
        self.btnClearWatermark.setObjectName(u"btnClearWatermark")
        self.btnClearWatermark.setCursor(Qt.PointingHandCursor)
        self.leftLayout.addWidget(self.btnClearWatermark)
        
        self.verticalSpacerLeft = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.leftLayout.addItem(self.verticalSpacerLeft)
        
        self.lblLocationTitle = QLabel(self.leftPanel)
        self.lblLocationTitle.setObjectName(u"lblLocationTitle")
        self.lblLocationTitle.setText(u"位置")
        self.leftLayout.addWidget(self.lblLocationTitle)
        
        # --- Right Panel: Task List & Dashboard ---
        self.rightPanel = QWidget(self.centralwidget)
        self.rightPanel.setObjectName(u"rightPanel")
        
        self.rightLayout = QVBoxLayout(self.rightPanel)
        self.rightLayout.setSpacing(20)
        self.rightLayout.setContentsMargins(30, 30, 30, 30)
        
        # Header Row
        self.headerLayout = QHBoxLayout()
        self.headerLayout.setSpacing(15)
        
        self.lblRightTitle = QLabel(self.rightPanel)
        self.lblRightTitle.setObjectName(u"lblRightTitle")
        self.lblRightTitle.setFont(font_title)
        self.headerLayout.addWidget(self.lblRightTitle)
        
        self.headerSpacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.headerLayout.addItem(self.headerSpacer)
        
        self.btnSelectFolder = QPushButton(self.rightPanel)
        self.btnSelectFolder.setObjectName(u"btnSelectFolder")
        self.btnSelectFolder.setCursor(Qt.PointingHandCursor)
        self.headerLayout.addWidget(self.btnSelectFolder)
        
        self.btnStartProcess = QPushButton(self.rightPanel)
        self.btnStartProcess.setObjectName(u"btnStartProcess")
        self.btnStartProcess.setCursor(Qt.PointingHandCursor)
        self.headerLayout.addWidget(self.btnStartProcess)

        self.btnStop = QPushButton(self.rightPanel)
        self.btnStop.setObjectName(u"btnStop")
        self.btnStop.setCursor(Qt.PointingHandCursor)
        self.btnStop.setEnabled(False) # 默认禁用
        self.headerLayout.addWidget(self.btnStop)
        
        self.rightLayout.addLayout(self.headerLayout)
        
        # Breadcrumb / Folder Bar
        self.folderBarLayout = QHBoxLayout()
        self.lblFolderIcon = QLabel(self.rightPanel)
        self.lblFolderIcon.setText(u"📂") 
        self.folderBarLayout.addWidget(self.lblFolderIcon)
        
        self.lblCurrentFolder = QLabel(self.rightPanel)
        self.lblCurrentFolder.setObjectName(u"lblCurrentFolder")
        self.lblCurrentFolder.setText(u"视频加水印")
        self.folderBarLayout.addWidget(self.lblCurrentFolder)
        
        self.folderSpacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.folderBarLayout.addItem(self.folderSpacer)
        
        self.lblFileCount = QLabel(self.rightPanel)
        self.lblFileCount.setObjectName(u"lblFileCount")
        self.lblFileCount.setStyleSheet("color: #0078d4; background-color: #e5f3ff; padding: 4px 8px; border-radius: 12px;")
        self.folderBarLayout.addWidget(self.lblFileCount)
        
        self.rightLayout.addLayout(self.folderBarLayout)
        
        # Stats Dashboard
        self.statsFrame = QFrame(self.rightPanel)
        self.statsFrame.setObjectName(u"statsFrame")
        self.statsLayout = QHBoxLayout(self.statsFrame)
        self.statsLayout.setContentsMargins(0, 10, 0, 10)
        
        # Total
        self.statTotalLayout = self._create_stat_widget(MainWindow, "Total", u"总计", "0", "📄")
        self.statsLayout.addLayout(self.statTotalLayout)
        self.statsLayout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        
        # Done
        self.statDoneLayout = self._create_stat_widget(MainWindow, "Done", u"完成", "0", "✅", "#28a745")
        self.statsLayout.addLayout(self.statDoneLayout)
        self.statsLayout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Fail
        self.statFailLayout = self._create_stat_widget(MainWindow, "Fail", u"失败", "0", "❌", "#dc3545")
        self.statsLayout.addLayout(self.statFailLayout)
        self.statsLayout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Skip
        self.statSkipLayout = self._create_stat_widget(MainWindow, "Skip", u"跳过", "0", "\U0001F232", "#ffc107")
        self.statsLayout.addLayout(self.statSkipLayout)
        
        self.statsLayout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        
        self.btnReset = QPushButton(self.rightPanel)
        self.btnReset.setObjectName(u"btnReset")
        self.btnReset.setText(u"\U0001F504 重新开始")
        self.btnReset.setCursor(Qt.PointingHandCursor)
        self.statsLayout.addWidget(self.btnReset)
        
        self.rightLayout.addWidget(self.statsFrame)
        self.statsFrame.hide() # 默认隐藏，处理完再显示
        
        # Table
        self.tableFiles = QTableWidget(self.rightPanel)
        if (self.tableFiles.columnCount() < 5):
            self.tableFiles.setColumnCount(5)
        
        headers = [u"文件名", u"格式", u"大小", u"进度", u"状态"]
        for i, h in enumerate(headers):
            item = QTableWidgetItem()
            item.setText(h)
            self.tableFiles.setHorizontalHeaderItem(i, item)
            
        self.tableFiles.setObjectName(u"tableFiles")
        self.tableFiles.horizontalHeader().setStretchLastSection(True)
        self.tableFiles.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tableFiles.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tableFiles.setColumnWidth(1, 80)
        self.tableFiles.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.tableFiles.setColumnWidth(2, 100)
        self.tableFiles.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.tableFiles.setColumnWidth(4, 80)
        
        self.tableFiles.verticalHeader().setVisible(False)
        self.tableFiles.setShowGrid(False)
        self.tableFiles.setAlternatingRowColors(True)
        self.tableFiles.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableFiles.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tableFiles.setContextMenuPolicy(Qt.CustomContextMenu)
        
        self.rightLayout.addWidget(self.tableFiles)
        
        # Main Layout Assembly
        self.mainLayout.addWidget(self.leftPanel)
        self.mainLayout.addWidget(self.rightPanel)
        
        MainWindow.setCentralWidget(self.centralwidget)
        
        # Actions
        self.actionSettings = QAction(MainWindow)
        self.actionSettings.setObjectName(u"actionSettings")
        self.actionExit = QAction(MainWindow)
        self.actionExit.setObjectName(u"actionExit")
        self.actionClearHistory = QAction(MainWindow)
        self.actionClearHistory.setObjectName(u"actionClearHistory")
        self.actionHelp = QAction(MainWindow)
        self.actionHelp.setObjectName(u"actionHelp")
        self.actionAbout = QAction(MainWindow)
        self.actionAbout.setObjectName(u"actionAbout")
        
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1100, 22))
        
        self.menuFile = QMenu(self.menubar)
        self.menuFile.setObjectName(u"menuFile")
        
        self.menuHelp = QMenu(self.menubar)
        self.menuHelp.setObjectName(u"menuHelp")
        
        MainWindow.setMenuBar(self.menubar)
        
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)
        
        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuHelp.menuAction())
        
        self.menuFile.addAction(self.actionSettings)
        self.menuFile.addAction(self.actionClearHistory)
        self.menuFile.addSeparator()
        self.menuFile.addAction(self.actionExit)
        
        self.menuHelp.addAction(self.actionHelp)
        self.menuHelp.addAction(self.actionAbout)

        self.retranslateUi(MainWindow)
        QMetaObject.connectSlotsByName(MainWindow)

    def _create_stat_widget(self, MainWindow, name, label, value, icon, color=None):
        layout = QVBoxLayout()
        lbl_title = QLabel(label)
        lbl_title.setStyleSheet("color: #888;")
        
        hbox = QHBoxLayout()
        lbl_icon = QLabel(icon)
        if color:
             lbl_icon.setStyleSheet(f"color: {color}; font-size: 16px;")
        
        lbl_val = QLabel(value)
        # 将 Label 直接赋值给 MainWindow (即 self)，使其可被外部访问
        setattr(MainWindow, f"statValue_{name}", lbl_val)
        
        lbl_val.setObjectName(f"statValue_{name}") 
        lbl_val.setStyleSheet("font-size: 18px; font-weight: bold;")
        
        hbox.addWidget(lbl_icon)
        hbox.addWidget(lbl_val)
        
        layout.addWidget(lbl_title)
        layout.addLayout(hbox)
        return layout

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u89c6\u9891\u6c34\u5370\u5de5\u5177", None))
        self.lblLeftTitle.setText(QCoreApplication.translate("MainWindow", u"\u6c34\u5370\u8bbe\u7f6e", None))
        self.lblPreviewTitle.setText(QCoreApplication.translate("MainWindow", u"\u9884\u89c8", None))
        self.btnClearWatermark.setText(QCoreApplication.translate("MainWindow", u"\u2421 \u6e05\u9664\u6c34\u5370", None))
        
        self.lblRightTitle.setText(QCoreApplication.translate("MainWindow", u"\u89c6\u9891\u6c34\u5370\u5de5\u5177", None))
        self.btnSelectFolder.setText(QCoreApplication.translate("MainWindow", u"\U0001F4C1 \u9009\u62e9\u6587\u4ef6\u5939", None))
        self.btnStartProcess.setText(QCoreApplication.translate("MainWindow", u"\u25b6 \u5f00\u59cb\u5904\u7406", None))
        self.btnStop.setText(QCoreApplication.translate("MainWindow", u"\u23f9 \u505c\u6b62", None))
        self.lblFileCount.setText(QCoreApplication.translate("MainWindow", u"0 \u4e2a\u89c6\u9891", None))
        
        self.menuFile.setTitle(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6", None))
        self.actionSettings.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e (Preferences)...", None))
        self.actionClearHistory.setText(QCoreApplication.translate("MainWindow", u"\u6e05\u7a7a\u5904\u7406\u5386\u53f2", None))
        self.actionExit.setText(QCoreApplication.translate("MainWindow", u"\u9000\u51fa", None))
        
        self.menuHelp.setTitle(QCoreApplication.translate("MainWindow", u"\u5e2e\u52a9", None))
        self.actionHelp.setText(QCoreApplication.translate("MainWindow", u"\u4f7f\u7528\u5e2e\u52a9", None))
        self.actionAbout.setText(QCoreApplication.translate("MainWindow", u"\u5173\u4e8e\u8f6f\u4ef6", None))
