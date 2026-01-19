#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
import colorsys
import subprocess

from PIL import Image
from pathlib import Path
from typing import Optional, List
from .logger import logger

def which_or_none(name: str) -> Optional[str]:
    """查找可执行文件路径"""
    try:
        return shutil.which(name)
    except Exception:
        return None

def check_ffmpeg() -> tuple[Optional[str], Optional[str]]:
    """
    返回 (ffmpeg_path, ffprobe_path)
    优先级：1. 程序目录下的 tools 文件夹  2. 系统环境变量 (PATH)
    """
    try:
        base_dir = Path(__file__).resolve().parent.parent.parent
        tools_dir = base_dir / "tools"
        
        ffmpeg_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        ffprobe_name = "ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"
        
        local_ffmpeg = tools_dir / ffmpeg_name
        local_ffprobe = tools_dir / ffprobe_name
        
        ffmpeg_path = str(local_ffmpeg) if local_ffmpeg.exists() else which_or_none("ffmpeg")
        ffprobe_path = str(local_ffprobe) if local_ffprobe.exists() else which_or_none("ffprobe")
        
        return ffmpeg_path, ffprobe_path
    except Exception as e:
        logger.warning(f"本地 FFmpeg 探测失败 (将降级为系统 PATH): {e}")
        return which_or_none("ffmpeg"), which_or_none("ffprobe")

def to_ffmpeg_filter_path(path: str) -> str:
    """
    将路径转换为更适合 FFmpeg filter 参数的形式：
    - 统一为绝对路径
    - 统一为正斜杠（Windows 也支持）
    - 转义单引号
    - 转义冒号（防止被识别为协议）
    """
    p = os.path.abspath(path)
    p = p.replace("\\", "/")
    p = p.replace("'", r"\'")
    p = p.replace(":", r"\:")
    return p

def default_font_path() -> Optional[str]:
    """
    尝试找到一个比较通用的字体文件（支持中英文更好）。
    """
    candidates = []
    if sys.platform.startswith("win"):
        candidates += [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    elif sys.platform == "darwin":
        candidates += [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def find_font_path(font_name: str) -> Optional[str]:
    """
    根据字体名称（家族名）尝试寻找对应的字体文件路径。
    目前主要针对 Windows 常见的字体存放方式。
    """
    if not font_name:
        return default_font_path()

    if sys.platform.startswith("win"):
        font_dir = r"C:\Windows\Fonts"
        try:
            for f in os.listdir(font_dir):
                if f.lower().endswith((".ttf", ".ttc", ".otf")):
                    if font_name.lower() in f.lower().replace(" ", ""):
                        return os.path.join(font_dir, f)
        except:
            pass
            
    return default_font_path()

def is_video_file(path: str) -> bool:
    """简单判断是否为视频文件"""
    VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".m4v", ".webm", ".ts"}
    return Path(path).suffix.lower() in VIDEO_EXTS

def is_image_file(path: str) -> bool:
    """简单判断是否为图片文件"""
    IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    return os.path.splitext(path)[1].lower() in IMG_EXTS

def get_available_encoders() -> List[str]:
    """获取可用编码器列表，支持更多 GPU 编码器类型"""
    ffmpeg, _ = check_ffmpeg()
    if not ffmpeg:
        return []
    
    encoders = []
    try:
        res = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            errors='ignore',
            shell=True
        )
        output = res.stdout

        if re.search(r"h264_nvenc", output, re.I): encoders.append("h264_nvenc")
        if re.search(r"h264_qsv", output, re.I): encoders.append("h264_qsv")
        if re.search(r"h264_amf", output, re.I): encoders.append("h264_amf")
        
    except Exception as e:
        logger.error(f"探测 GPU 编码器失败: {e}")
        
    return encoders

def analyze_smart_colors(image_path: str, x: int, y: int, w: int, h: int) -> tuple[str, str]:
    """
    智能分析指定区域的最佳文字颜色和描边颜色。
    参数:
        image_path: 采样帧图片路径
        x, y, w, h: 采样区域(水印可能占据的范围)
    返回:
        (font_color_hex, border_color_hex)
    """
    try:
        with Image.open(image_path) as img:
            img_w, img_h = img.size
            x1 = max(0, min(x, img_w - 1))
            y1 = max(0, min(y, img_h - 1))
            x2 = max(x1 + 1, min(x + w, img_w))
            y2 = max(y1 + 1, min(y + h, img_h))
            roi = img.crop((x1, y1, x2, y2))
            roi = roi.resize((1, 1), resample=Image.Resampling.BOX)
            r, g, b = roi.getpixel((0, 0))[:3]

        h_val, l_val, s_val = colorsys.rgb_to_hls(r/255.0, g/255.0, b/255.0)

        target_h = (h_val + 0.5) % 1.0

        if l_val > 0.6:
            target_l = 0.15 + (l_val * 0.1)
            target_s = min(1.0, s_val + 0.3)
        elif l_val < 0.4:
            target_l = 0.85 - (l_val * 0.1)
            target_s = min(1.0, s_val + 0.2)
        else:
            target_l = 1.0 - l_val 
            target_s = 1.0

        border_l = 1.0 if target_l < 0.5 else 0.0

        fr, fg, fb = colorsys.hls_to_rgb(target_h, target_l, target_s)
        br, bg, bb = colorsys.hls_to_rgb(0, border_l, 0)
        
        def to_hex(rgb):
            return '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            
        return to_hex((fr, fg, fb)), to_hex((br, bg, bb))
        
    except Exception as e:
        logger.error(f"智能选色分析失败: {e}")
        return "#FFFFFF", "#000000"

def get_gpu_params(encoders: List[str], crf: int, preset: str) -> List[str]:
    """
    根据可用编码器列表，返回最优的 GPU 编码参数。
    优先级：NVENC > QSV > AMF
    """
    if "h264_nvenc" in encoders:
        return ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", str(crf), "-preset", "p4"]
    
    if "h264_qsv" in encoders:
        return ["-c:v", "h264_qsv", "-global_quality", str(crf), "-preset", "balanced"]
    
    if "h264_amf" in encoders:
        return ["-c:v", "h264_amf", "-rc", "vbr_latency", "-quality", "balanced"]

    return ["-c:v", "libx264", "-crf", str(crf), "-preset", preset]
