# -*- coding: utf-8 -*-
import os
import sys
import zipfile
if sys.platform == "win32":
    import winreg
import shutil
import urllib.request
from pathlib import Path

from video_watermarker_app.utils.logger import logger
from video_watermarker_app.utils.common import check_ffmpeg

from GLOBAL import APP_EN_NAME, FFMPEG_URL


class FFmpegInstaller:
    """
    负责 FFmpeg 的下载、安装和环境变量配置。
    """

    def __init__(self):
        # 安装目录: %APPDATA%/VideoWatermarker/bin
        app_data = os.getenv('APPDATA')
        if not app_data:
            app_data = os.path.expanduser("~")
        
        self.install_dir = Path(app_data) / APP_EN_NAME / "bin"
        self.temp_zip = Path(app_data) / APP_EN_NAME / "ffmpeg_temp.zip"

    def is_installed(self) -> bool:
        """检查 FFmpeg 是否已安装或在 PATH 中可用"""
        ffmpeg, _ = check_ffmpeg()
        if ffmpeg:
            return True
        
        # 检查本地安装目录是否已有
        if self._find_local_ffmpeg():
            return True
            
        return False

    def _find_local_ffmpeg(self):
        """检查安装目录是否有 ffmpeg.exe"""
        if not self.install_dir.exists():
            return None
            
        # 查找 bin 目录下的 ffmpeg.exe (解压后通常在 ffmpeg-x.x-essentials_build/bin)
        target = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        for path in self.install_dir.rglob(target):
            return path
        return None

    def install(self, progress_callback=None) -> bool:
        """
        执行安装流程: 下载 -> 解压 -> 配置路径
        progress_callback(int, str): 进度回调 (0-100, 描述)
        """
        try:
            self.install_dir.parent.mkdir(parents=True, exist_ok=True)
            
            # 1. 下载
            if progress_callback:
                progress_callback(0, "正在下载 FFmpeg...")
            
            self._download(progress_callback)
            
            # 2. 解压
            if progress_callback:
                progress_callback(50, "正在解压...")
            
            self._extract()
            
            # 3. 查找并设置路径
            if progress_callback:
                progress_callback(90, "正在配置环境...")
            
            bin_path = self._configure_path()
            
            if progress_callback:
                progress_callback(100, "安装完成")
                
            return True
            
        except Exception as e:
            logger.error(f"FFmpeg install failed: {e}")
            if progress_callback:
                progress_callback(0, f"安装失败: {e}")
            return False
        finally:
            # 清理临时文件
            if self.temp_zip.exists():
                try:
                    os.remove(self.temp_zip)
                except OSError:
                    pass

    def _download(self, progress_callback):
        """使用 urllib 下载，支持进度显示"""
        def report(block_num, block_size, total_size):
            if total_size <= 0:
                p = 0
            else:
                downloaded = block_num * block_size
                p = int(downloaded / total_size * 50) # 这里的进度算 0-50%
                p = min(p, 50)
            
            if progress_callback:
                # 为了避免频繁回调，可以加判断，这里直接调
                progress_callback(p, f"正在下载... {p*2}%")

        logger.info(f"Downloading FFmpeg from {FFMPEG_URL}")
        urllib.request.urlretrieve(FFMPEG_URL, self.temp_zip, report)

    def _extract(self):
        """解压 Zip 文件"""
        logger.info("Extracting FFmpeg...")
        # 清理旧目录
        if self.install_dir.exists():
            shutil.rmtree(self.install_dir)
        
        with zipfile.ZipFile(self.temp_zip, 'r') as zip_ref:
            zip_ref.extractall(self.install_dir)

        if sys.platform != "win32":
            # 赋予可执行权限
            exe_path = self._find_local_ffmpeg()
            if exe_path and exe_path.exists():
                os.chmod(exe_path, 0o755)
                ffprobe_path = exe_path.parent / "ffprobe"
                if ffprobe_path.exists():
                    os.chmod(ffprobe_path, 0o755)

    def _configure_path(self):
        """配置环境变量"""
        # 找到 bin 文件夹
        exe_path = self._find_local_ffmpeg()
        if not exe_path:
            raise FileNotFoundError("解压后未找到 ffmpeg.exe")
            
        bin_dir = str(exe_path.parent)
        
        # 1. 设置当前进程 PATH，使其立即生效
        os.environ["PATH"] += os.pathsep + bin_dir
        logger.info(f"Added to process PATH: {bin_dir}")
        
        # 2. 尝试设置用户级环境变量 (永久生效)
        if sys.platform == "win32":
            try:
                self._add_to_user_path(bin_dir)
            except Exception as e:
                logger.warning(f"Failed to set user PATH registry: {e}")
                # 不阻断流程，至少当前次能用
            
        return bin_dir

    def _add_to_user_path(self, new_path):
        """将路径添加到 Windows 用户环境变量 PATH"""
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, 
            r"Environment", 
            0, 
            winreg.KEY_ALL_ACCESS
        )
        try:
            path_val, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            path_val = ""
            
        if new_path.lower() in path_val.lower():
            logger.info("Path already exists in registry.")
            winreg.CloseKey(key)
            return

        # 添加
        if path_val:
            new_path_val = path_val + ";" + new_path
        else:
            new_path_val = new_path
            
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path_val)
        winreg.CloseKey(key)
        logger.info("Updated Registry User PATH.")
