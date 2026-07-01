#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
import subprocess
import colorsys

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

def get_sp_kwargs() -> dict:
    """获取跨平台且在 Windows 下隐藏黑框的 subprocess 参数字典"""
    kwargs = {'shell': False}
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs['startupinfo'] = startupinfo
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    return kwargs

def check_ffmpeg() -> tuple[Optional[str], Optional[str]]:
    """
    返回 (ffmpeg_path, ffprobe_path)
    优先级：1. 程序目录下的 tools 文件夹  2. 系统环境变量 (PATH)
    """
    try:
        # common.py 位于 {ROOT}/video_watermarker_app/utils/common.py
        # 我们向上回溯三级找到 ROOT
        base_dir = Path(__file__).resolve().parent.parent.parent
        tools_dir = base_dir / "tools"

        ffmpeg_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        ffprobe_name = "ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"

        local_ffmpeg = tools_dir / ffmpeg_name
        local_ffprobe = tools_dir / ffprobe_name

        ffmpeg_path = str(local_ffmpeg) if local_ffmpeg.exists() else which_or_none("ffmpeg")
        ffprobe_path = str(local_ffprobe) if local_ffprobe.exists() else which_or_none("ffprobe")

        # Fallback for macOS GUI apps where PATH might not include /usr/local/bin
        if sys.platform == "darwin":
            mac_paths = ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin"]
            if not ffmpeg_path:
                for p in mac_paths:
                    candidate = Path(p) / "ffmpeg"
                    if candidate.exists() and os.access(candidate, os.X_OK):
                        ffmpeg_path = str(candidate)
                        break
            if not ffprobe_path:
                for p in mac_paths:
                    candidate = Path(p) / "ffprobe"
                    if candidate.exists() and os.access(candidate, os.X_OK):
                        ffprobe_path = str(candidate)
                        break

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
    # 对于 FFmpeg 滤镜字符串中的路径：
    # 1. 统一为正斜杠（Windows 也支持）
    # 2. 只需要转义单引号 (因为参数通常被单引号包裹)
    # 3. 冒号转义在特定版本的 drawtext 里需要，但在其他地方可能会破坏路径。
    # 按照 FFmpeg 官方建议，使用反斜杠转义单引号和冒号是最稳妥的。
    p = p.replace("\\", "/")
    p = p.replace("'", r"\'")
    # 对于冒号，如果不进行特殊处理，C:/... 可能会被解释为协议。
    # 在 filter_complex 中，双反斜杠转义是较好的实践： C\\:/...
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
        
    # Windows 字体名与文件名的部分对应关系（硬编码常见的情况，或者扫描）
    if sys.platform.startswith("win"):
        font_dir = r"C:\Windows\Fonts"
        # 简单扫描匹配：先找包含名称的
        try:
            for f in os.listdir(font_dir):
                if f.lower().endswith((".ttf", ".ttc", ".otf")):
                    # 这里是一个简单的模糊匹配，如果真正精确需要解析字体文件头，
                    # 考虑到性能和依赖，先做简单的匹配。
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
        # 使用 errors='ignore' 防止 Windows 某些环境下的编码解码报错导致闪退
        res = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            errors='ignore',
            **get_sp_kwargs()
        )
        output = res.stdout
        
        # 匹配 H.264 的各种硬件实现
        if re.search(r"h264_nvenc", output, re.I): encoders.append("h264_nvenc")
        if re.search(r"h264_qsv", output, re.I): encoders.append("h264_qsv")
        if re.search(r"h264_amf", output, re.I): encoders.append("h264_amf")
        
    except Exception as e:
        logger.error(f"探测 GPU 编码器失败: {e}")
        
    return encoders

def get_gpu_params(encoders: List[str], crf: int, preset: str) -> List[str]:
    """
    根据可用编码器列表，返回最优的 GPU 编码参数。
    优先级：NVENC > QSV > AMF
    """
    if "h264_nvenc" in encoders:
        # NVIDIA: -cq 用于质量控制, -preset 为 p1~p7 (或者 faster/slow 等兼容名)
        return ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", str(crf), "-preset", "p4"]
    
    if "h264_qsv" in encoders:
        # Intel: -global_quality
        return ["-c:v", "h264_qsv", "-global_quality", str(crf), "-preset", "balanced"]
    
    if "h264_amf" in encoders:
        # AMD
        return ["-c:v", "h264_amf", "-rc", "vbr_latency", "-quality", "balanced"]
    
    # 兜底
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", preset]

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
            # 裁剪区域 (left, top, right, bottom)
            img_w, img_h = img.size
            # 简单边界检查
            x1 = max(0, min(x, img_w - 1))
            y1 = max(0, min(y, img_h - 1))
            x2 = max(x1 + 1, min(x + w, img_w))
            y2 = max(y1 + 1, min(y + h, img_h))

            roi = img.crop((x1, y1, x2, y2))
            # 缩放为 1x1 获取平均颜色，这是最快的方法
            roi = roi.resize((1, 1), resample=Image.Resampling.BOX)
            r, g, b = roi.getpixel((0, 0))[:3]

        # 转换为 HSL (0-1)
        h_val, l_val, s_val = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

        # 1. 计算补色 (色相旋转 180 度)
        target_h = (h_val + 0.5) % 1.0

        # 2. 根据背景明度调整目标文字的明度和饱和度
        # 如果背景很亮 (L > 0.6)，文字应偏暗；如果背景很暗 (L < 0.4)，文字应偏亮。
        if l_val > 0.6:
            target_l = 0.15 + (l_val * 0.1)  # 强制深色
            target_s = min(1.0, s_val + 0.3)  # 增加饱和度使其跳出
        elif l_val < 0.4:
            target_l = 0.85 - (l_val * 0.1)  # 强制浅色
            target_s = min(1.0, s_val + 0.2)
        else:
            # 中等亮度背景，使用纯补色，并根据对比度微调
            target_l = 1.0 - l_val
            target_s = 1.0

        # 3. 计算描边色 (通常与背景主色相近但明度相反，或者纯黑/白)
        border_l = 1.0 if target_l < 0.5 else 0.0

        # 转回 RGB
        fr, fg, fb = colorsys.hls_to_rgb(target_h, target_l, target_s)
        br, bg, bb = colorsys.hls_to_rgb(0, border_l, 0)

        def to_hex(rgb):
            return '#%02x%02x%02x' % (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))

        return to_hex((fr, fg, fb)), to_hex((br, bg, bb))

    except Exception as e:
        logger.error(f"智能选色分析失败: {e}")
        return "#FFFFFF", "#000000"


def calc_auto_font_size(text: str, img_width: int, img_height: int,
                        margin: int = 20, font_name: str = "") -> int:
    """
    根据画面尺寸和水印文字，自动计算最佳字号。
    用于"上中"和"下中"位置，确保文字完整居中显示且清晰可见。

    核心策略：使用 PIL ImageFont 实际测量文字渲染宽度，
    二分搜索最大的字号，使文字宽度 ≤ 可用宽度 × 85%。
    PIL 不可用时使用保守估算兜底。

    参数:
        text: 水印文字内容
        img_width: 画面宽度
        img_height: 画面高度
        margin: 边距
        font_name: 字体名称（用于匹配实际渲染字体）
    """
    if not text:
        return max(16, int(img_height * 0.03))

    available_width = max(1, img_width - 2 * margin)
    # 目标：文字宽度 ≤ 可用宽度的 85%
    target_width = int(available_width * 0.85)

    # 字号搜索范围
    min_fs = max(12, int(img_height * 0.015))
    max_fs = max(min_fs + 1, int(img_height * 0.08))

    # 获取字体文件路径（用于 PIL 精确测量）
    font_path = find_font_path(font_name)

    try:
        from PIL import ImageFont

        # 缓存字体对象，避免循环中反复从磁盘加载
        _font_cache = {}

        def _measure_width(fs):
            """用 PIL 精确测量指定字号下文字的渲染像素宽度"""
            try:
                if fs not in _font_cache:
                    if font_path and os.path.exists(font_path):
                        _font_cache[fs] = ImageFont.truetype(font_path, fs)
                    else:
                        _font_cache[fs] = ImageFont.load_default()
                font = _font_cache[fs]
                bbox = font.getbbox(text)
                return bbox[2] - bbox[0]
            except Exception:
                return None

        # 二分搜索：找到最大的字号使 text_width ≤ target_width
        best_fs = min_fs
        lo, hi = min_fs, max_fs

        while lo <= hi:
            mid = (lo + hi) // 2
            tw = _measure_width(mid)
            if tw is None:
                # 测量失败，放弃 PIL 走兜底
                raise RuntimeError("PIL 测量失败")

            if tw <= target_width:
                best_fs = mid
                lo = mid + 1
            else:
                hi = mid - 1

        # 释放缓存的字体对象
        _font_cache.clear()
        return best_fs

    except Exception as e:
        # PIL 不可用或测量失败，使用保守估算
        logger.warning(f"PIL 精确测量不可用，使用保守估算: {e}")

        effective_chars = 0.0
        for ch in text:
            if ord(ch) > 0x2E80:
                effective_chars += 1.0
            elif ch == ' ':
                effective_chars += 0.35
            elif ch.isupper():
                effective_chars += 0.75
            else:
                effective_chars += 0.6

        if effective_chars <= 0:
            effective_chars = 1.0

        font_size = int(target_width / effective_chars)
        # 兜底时用更保守的上限
        fallback_max = max(min_fs + 1, min(int(img_height * 0.05), int(img_width * 0.08)))
        return max(min_fs, min(font_size, fallback_max))


