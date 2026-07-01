#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from GLOBAL import APP_VER

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("用户手册与使用说明")
        self.resize(800, 600)
        self.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(self)
        
        # 头部
        header_layout = QHBoxLayout()
        title_label = QLabel("<h3>📘 多媒体水印助手 - 完整帮助指南</h3>")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # 内容区域
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(self._get_help_content())
        layout.addWidget(self.browser)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btnClose = QPushButton("我知道了")
        self.btnClose.setFixedWidth(100)
        self.btnClose.clicked.connect(self.accept)
        btn_layout.addWidget(self.btnClose)
        layout.addLayout(btn_layout)
        
        self.setStyleSheet("""
            QDialog { background-color: #f9f9f9; }
            QTextBrowser { 
                background-color: white; 
                border: 1px solid #ddd; 
                border-radius: 4px; 
                padding: 15px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                line-height: 1.6;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #106ebe; }
        """)

    def _get_help_content(self):
        html = """
        <style>
            h2 { color: #0078d4; border-bottom: 2px solid #0078d4; padding-bottom: 5px; margin-top: 25px; }
            h3 { color: #333; margin-top: 20px; }
            code { background-color: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; }
            table { border-collapse: collapse; width: 100%; margin: 15px 0; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
            th { background-color: #f2f2f2; }
            .tip { background-color: #e5f3ff; border-left: 5px solid #0078d4; padding: 10px; margin: 15px 0; }
            .warning { background-color: #fff4ce; border-left: 5px solid #ffb900; padding: 10px; margin: 15px 0; }
        </style>

        <h2>🚀 1. 快速上手</h2>
        <p>欢迎使用多媒体水印助手！只需三步即可开始批量处理：</p>
        <ol>
            <li><b>添加文件：</b>点击主界面右上角的“选择文件夹”或将文件/文件夹拖入任务列表。</li>
            <li><b>水印配置：</b>在侧边栏即时调整位置、大小、透明度。点击预览图可进入全屏对比。</li>
            <li><b>一键处理：</b>点击“开始处理”，程序将自动按队列处理所有未完成的任务。</li>
        </ol>

        <h2>🎨 2. 水印功能详解</h2>
        <h3>🖼️ 图片水印</h3>
        <ul>
            <li>支持 <code>PNG</code> (含透明通道)、<code>JPG</code>、<code>WEBP</code> 等主流格式。</li>
            <li><b>羽化半径：</b> 专门针对不规则边缘设计的抗锯齿功能。如果您的 LOGO 边缘有白边，尝试增大此值。</li>
        </ul>
        <h3>✍️ 文字水印</h3>
        <ul>
            <li><b>智能调色 (Magic Color)：</b> 开启后，程序将通过 AI 采样视频背景色，自动为您选择对比度最高的文字颜色及描边，确保在任何背景下水印都清晰可见。</li>
            <li><b>文字变色：</b> 支持为文字水印动态设置变色效果，您可以指定文字在特定的时间段内、甚至按照关键帧实现平滑的颜色过渡，让您的水印更加灵动出彩。</li>
            <li><b>字体选择：</b> 支持调用系统字体库。推荐使用粗体。支持动态缩放，确保不同分辨率下的视觉一致性。对比度不够时可尝试开启“智能调色”。</li>
        </ul>

        <h2>⚙️ 3. 输出与便携性</h2>
        <ul>
            <li><b>原地替换 (In-place)：</b> 开启此项后，处理结果将直接覆盖原视频/图片。程序采用安全原子操作，确保渲染成功后才会执行替换，防止数据丢失。</li>
            <li><b>并发处理：</b> 支持 1-4 个任务同时渲染，充分利用多核 CPU 性能。</li>
            <li><b>绿色便携：</b> 程序自带优化版 FFmpeg 核心，无需在系统中安装任何额外软件即可直接运行。</li>
        </ul>

        <h2>⚡ 4. GPU 硬件加速</h2>
        <div class="tip">开启 GPU 加速可将转换速度提升 3-10 倍。核心代码已针对 NVENC、QSV 及 AMF 进行了全平台适配。</div>
        <table>
            <tr><th>显卡厂商</th><th>对应编码器名称</th><th>适用场景</th></tr>
            <tr><td>NVIDIA</td><td>h264_nvenc</td><td>GTX/RTX 系列，性能王者。</td></tr>
            <tr><td>Intel</td><td>h264_qsv</td><td>酷睿系列核显，低功耗首选。</td></tr>
            <tr><td>AMD</td><td>h264_amf</td><td>Radeon 系列，高效稳定。</td></tr>
        </table>

        <h2>💾 5. 模板系统与存储</h2>
        <p>您可以将常用的水印配置保存为模板：</p>
        <ul>
            <li>在设置中选择模板后，<b>任何修改都会在点击“确定”时自动同步到该模板</b>，无需手动保存。</li>
            <li><b>记忆功能：</b> 程序会记住您上次关闭时选中的模板，下次启动将自动恢复所有设置。</li>
        </ul>

        <h2>❓ 6. 常见问题与排查</h2>
        <div class="warning">
            <b>Q: 处理失败显示详细错误？</b><br>
            A: 我们增强了日志捕获功能，现在失败后会将 FFmpeg 的具体报错（如“格式不支持”、“文件占用”等）直接显示在状态栏提示中，方便快速定位问题。
        </div>
        <div class="warning">
            <b>Q: 开启智能调色后预览图没变？</b><br>
            A: 预览图为静态模拟。智能调色会在实际渲染任务开始时执行逐帧/采样分析，以最终输出结果为准。
        </div>

        <h2>📞 6. 技术支持</h2>
        <p>如果您在使用过程中遇到任何 Bug 或有功能建议，请通过以下方式联系：</p>
        <ul>
            <li>提交反馈: <a href="https://forms.gle/P1DGfsRaYNvVR6SA7">https://forms.gle/P1DGfsRaYNvVR6SA7</a></li>
        </ul>
        <p style="text-align: center; color: #888; font-size: 0.9em; margin-top: 30px;">
            多媒体水印助手 v{APP_VER} Pro © 2026 SMILEY
        </p>
        """
        return html.replace("{APP_VER}", APP_VER)
