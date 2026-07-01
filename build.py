# OpenTimeLog 跨平台构建脚本
# 支持 Windows, macOS, Linux
# 依赖: pip install pyinstaller

import os
import sys
import shutil
import platform
import subprocess

def clean_build():
    """清理之前的构建目录"""
    print("清理旧的构建文件...")
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for d in dirs_to_clean:
        if os.path.exists(d):
            shutil.rmtree(d)
    
    # 清理 .spec 文件
    for f in os.listdir('.'):
        if f.endswith('.spec'):
            os.remove(f)

def build():
    """执行构建流程"""
    system = platform.system()
    print(f"检测到操作系统: {system}")
    
    # === 基础参数 ===
    base_args = [
        'pyinstaller',
        '--name=MediaWatermark',
        '--noconfirm',
        '--clean'
    ]
    
    # === Windows 打包 ===
    if system == 'Windows':
        print("开始 Windows 打包...")
        args = base_args + [
            '--windowed',  # 不显示控制台
            '--icon=app_icon.ico',
            'main.py'
        ]
        
    # === macOS 打包 ===
    elif system == 'Darwin':
        print("开始 macOS 打包...")
        args = base_args + [
            '--windowed',
            '--icon=app_icon.png',  # macOS 使用 png 或 icns
            'main.py'
        ]
        
    # === Linux 打包 ===
    elif system == 'Linux':
        print("开始 Linux 打包...")
        args = base_args + [
            '--windowed',
            '--icon=app_icon.png',
            'main.py'
        ]
        
    else:
        print(f"不支持的操作系统: {system}")
        sys.exit(1)
        
    # 执行构建
    print(" ".join(args))
    subprocess.run(args, check=True)
    
    print("🎉 构建完成！产物位于 dist/ 目录下。")

if __name__ == '__main__':
    # 确保在项目根目录运行
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    clean_build()
    build()
