#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
视频/图片文字变色核心工作线程模块。
将 foreground_color_filter.py 的算法逻辑封装为 QObject Worker，
支持批量处理、信号回报进度与状态。
"""

import os
import cv2
import numpy as np
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from video_watermarker_app.utils.logger import logger


# ══════════════════════════════════════════════════════
#  颜色工具
# ══════════════════════════════════════════════════════

def hex_to_bgr(hex_color: str) -> np.ndarray:
    """'#RRGGBB' → numpy array [B, G, R]"""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return np.array([b, g, r], dtype=float)


def parse_color(color) -> np.ndarray:
    """接受 '#RRGGBB'、(R,G,B) 或 (B,G,R) numpy array，统一返回 BGR float array"""
    if isinstance(color, str):
        return hex_to_bgr(color)
    arr = np.array(color, dtype=float)
    return arr


def derive_light_color(dark_bgr: np.ndarray, lightness: float = 0.72) -> np.ndarray:
    """
    从暗色自动推导蒙版底色（浅版）。
    原理：在Lab空间把L值拉高到 lightness*100，保留色相和饱和度。
    """
    pixel = dark_bgr.astype(np.uint8).reshape(1, 1, 3)
    lab = cv2.cvtColor(pixel, cv2.COLOR_BGR2Lab).astype(float)
    lab[0, 0, 0] = lightness * 100
    lab[0, 0, 1] *= 0.55
    lab[0, 0, 2] *= 0.55
    lab_u8 = np.clip(lab, 0, 255).astype(np.uint8)
    result = cv2.cvtColor(lab_u8, cv2.COLOR_Lab2BGR)
    return result.reshape(3).astype(float)


# ══════════════════════════════════════════════════════
#  蒙版检测：行投影法（毛玻璃/半透明蒙版）
# ══════════════════════════════════════════════════════

def _smooth(arr, w=5):
    """一维平滑滤波"""
    return np.convolve(arr, np.ones(w) / w, mode='same')


def _longest_run(bool_arr):
    """找最长连续True段，返回 (start, end)。"""
    best_s, best_l = 0, 0
    cur_s, cur_l = 0, 0
    for i, v in enumerate(bool_arr):
        if v:
            if cur_l == 0: cur_s = i
            cur_l += 1
            if cur_l > best_l:
                best_l = cur_l
                best_s = cur_s
        else:
            cur_l = 0
    return best_s, best_s + best_l


def detect_frosted_mask(
        frame_bgr,
        std_threshold=35,
        brightness_threshold=185,
        min_mask_ratio=0.04,
):
    """
    检测毛玻璃/半透明白色蒙版区域。
    特征：行内像素标准差低（颜色均匀）+ 行亮度高（接近白色）。
    返回：(mask uint8 H×W, bounds dict 或 None)
    """
    H, W = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(float)

    row_std = _smooth(gray.std(axis=1), 5)
    row_mean = _smooth(gray.mean(axis=1), 5)
    col_std = _smooth(gray.std(axis=0), 5)
    col_mean = _smooth(gray.mean(axis=0), 5)

    row_is_mask = (row_std < std_threshold) & (row_mean > brightness_threshold)
    col_is_mask = (col_std < std_threshold) & (col_mean > brightness_threshold)

    row_start, row_end = _longest_run(row_is_mask)
    col_start, col_end = _longest_run(col_is_mask)

    # 放宽重试
    if (row_end - row_start) < H * min_mask_ratio:
        row_is_mask = row_mean > brightness_threshold
        col_is_mask = col_mean > brightness_threshold
        row_start, row_end = _longest_run(row_is_mask)
        col_start, col_end = _longest_run(col_is_mask)

    if row_end <= row_start:
        return None, None

    # 列范围太窄 → 用全宽
    if (col_end - col_start) < W * 0.1:
        col_start, col_end = 0, W

    mask = np.zeros((H, W), dtype=np.uint8)
    mask[row_start:row_end, col_start:col_end] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

    bounds = dict(top=row_start, bottom=row_end, left=col_start, right=col_end)
    return mask, bounds


# ══════════════════════════════════════════════════════
#  核心滤镜：文字变色算法
# ══════════════════════════════════════════════════════

def recolor_text_only(
        frame_bgr,
        mask,
        target_color,
        text_brightness_thresh=130,
        edge_softness=8,
):
    """
    只改变文字颜色，蒙版底色完全不变。
    用 sigmoid 软权重提取暗色文字像素，Lab 空间只替换 a/b 色度通道。
    """
    h = target_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    target_bgr = np.array([b, g, r], dtype=float)

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(float)
    mask_float = mask.astype(float) / 255.0

    text_alpha = 1.0 / (1.0 + np.exp(
        (gray - text_brightness_thresh) / edge_softness
    ))
    text_alpha = text_alpha * mask_float

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2Lab).astype(float)
    target_lab = cv2.cvtColor(
        target_bgr.astype(np.uint8).reshape(1, 1, 3),
        cv2.COLOR_BGR2Lab
    ).astype(float)

    colored_lab = lab.copy()
    colored_lab[:, :, 1] = target_lab[0, 0, 1]
    colored_lab[:, :, 2] = target_lab[0, 0, 2]

    colored_bgr = cv2.cvtColor(
        np.clip(colored_lab, 0, 255).astype(np.uint8),
        cv2.COLOR_Lab2BGR
    ).astype(float)

    ta = text_alpha[:, :, np.newaxis]
    src = frame_bgr.astype(float)
    result = src * (1 - ta) + colored_bgr * ta
    return np.clip(result, 0, 255).astype(np.uint8)


def colorize_by_luminance(frame_bgr, mask, color, strength=0.85, feather=15):
    """
    通用文字变色滤镜（Lab亮度保留 + 任意颜色映射）。
    """
    H, W = frame_bgr.shape[:2]

    k = feather * 2 + 1
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (k, k), feather / 3) / 255.0

    dark_bgr = parse_color(color)
    light_bgr = derive_light_color(dark_bgr, lightness=0.75)

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2Lab).astype(float)
    L = lab[:, :, 0] / 100.0
    Lv = L[:, :, np.newaxis]

    color_layer = dark_bgr * (1.0 - Lv) + light_bgr * Lv

    src = frame_bgr.astype(float)
    mf = alpha[:, :, np.newaxis] * strength

    result = src * (1.0 - mf) + color_layer * mf
    return np.clip(result, 0, 255).astype(np.uint8)


def apply_filter_to_mask(
        frame_bgr,
        mask,
        mode='lab_colorize',
        color='#6600CC',
        strength=0.85,
        feather=15,
):
    """
    对蒙版区域叠加颜色滤镜。
    mode: 'lab_colorize'（推荐通用）, 'text_only'（仅改文字色）
    """
    color_bgr = parse_color(color)

    if mode == 'lab_colorize':
        return colorize_by_luminance(frame_bgr, mask, color_bgr, strength, feather)
    elif mode == 'text_only':
        return recolor_text_only(
            frame_bgr, mask,
            target_color=color,
            text_brightness_thresh=130,
            edge_softness=8,
        )
    else:
        # 默认使用 lab_colorize
        return colorize_by_luminance(frame_bgr, mask, color_bgr, strength, feather)


# ══════════════════════════════════════════════════════
#  视频处理
# ══════════════════════════════════════════════════════

def process_video(
        input_path,
        output_path,
        color='#6600CC',
        mode='lab_colorize',
        strength=0.85,
        feather=15,
        detect_every_n=0,
        fixed_bounds=None,
        std_threshold=35,
        brightness_threshold=185,
        codec='mp4v',
        progress_callback=None,
):
    """
    处理视频：自动检测蒙版区域，对文字应用颜色滤镜。
    progress_callback: 可选回调函数，接收 (当前帧, 总帧数) 参数
    """
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {input_path}")

    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    os.makedirs(Path(output_path).parent, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (W, H))

    # 构建固定蒙版
    fixed_mask = None
    if fixed_bounds:
        fixed_mask = np.zeros((H, W), dtype=np.uint8)
        t, b, l, r = fixed_bounds['top'], fixed_bounds['bottom'], fixed_bounds['left'], fixed_bounds['right']
        fixed_mask[t:b, l:r] = 255

    current_mask = fixed_mask
    detect_kw = dict(std_threshold=std_threshold, brightness_threshold=brightness_threshold)

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if fixed_mask is None:
            need = (current_mask is None or
                    (detect_every_n > 0 and frame_idx % detect_every_n == 0))
            if need:
                current_mask, bounds = detect_frosted_mask(frame, **detect_kw)

        if current_mask is not None:
            out = apply_filter_to_mask(
                frame, current_mask,
                mode=mode, color=color,
                strength=strength, feather=feather,
            )
        else:
            out = frame

        writer.write(out)
        frame_idx += 1

        # 回调进度
        if progress_callback and total > 0:
            progress_callback(frame_idx, total)

    cap.release()
    writer.release()

    # 尝试合并原视频音频
    import sys
    import subprocess
    from video_watermarker_app.utils.common import check_ffmpeg
    ffmpeg_exe, _ = check_ffmpeg()
    
    if ffmpeg_exe:
        temp_out = str(output_path) + ".temp_video.mp4"
        try:
            if os.path.exists(output_path):
                os.rename(output_path, temp_out)
                cmd = [
                    ffmpeg_exe, "-y", "-hide_banner",
                    "-i", temp_out,
                    "-i", str(input_path),
                    "-c:v", "copy",
                    "-c:a", "copy",
                    "-map", "0:v:0",
                    "-map", "1:a:0?",
                    str(output_path)
                ]
                
                startupinfo = None
                creationflags = 0
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    creationflags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, 'DETACHED_PROCESS', 0x00000008)
                
                subprocess.run(
                    cmd, 
                    check=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
        except Exception as e:
            logger.error(f"FFmpeg合并音频失败: {e}")
            if not os.path.exists(output_path) and os.path.exists(temp_out):
                os.rename(temp_out, output_path)
        finally:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except:
                    pass

    return output_path


def process_image(
        input_path,
        output_path,
        color='#6600CC',
        mode='lab_colorize',
        strength=0.85,
        feather=15,
        std_threshold=35,
        brightness_threshold=185,
        fixed_bounds=None,
):
    """对单张图片应用滤镜。"""
    img = cv2.imread(str(input_path))
    if img is None:
        raise ValueError(f"无法读取: {input_path}")
    H, W = img.shape[:2]

    if fixed_bounds:
        mask = np.zeros((H, W), dtype=np.uint8)
        t, b, l, r = fixed_bounds['top'], fixed_bounds['bottom'], fixed_bounds['left'], fixed_bounds['right']
        mask[t:b, l:r] = 255
    else:
        mask, bounds = detect_frosted_mask(
            img, std_threshold=std_threshold,
            brightness_threshold=brightness_threshold,
        )

    if mask is None:
        # 未检测到蒙版，对整图应用
        mask = np.ones((H, W), dtype=np.uint8) * 255

    result = apply_filter_to_mask(
        img, mask, mode=mode, color=color,
        strength=strength, feather=feather,
    )
    cv2.imwrite(str(output_path), result)
    return result


# ══════════════════════════════════════════════════════
#  预览工具函数
# ══════════════════════════════════════════════════════

def extract_video_frame(video_path, frame_sec=1.0):
    """
    从视频中提取指定秒数的帧，返回 BGR numpy array。
    提取失败返回 None。
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        target_frame = int(frame_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        if ret:
            return frame
        # 如果指定位置读取失败，尝试读取第一帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = cap.read()
        return frame if ret else None
    finally:
        cap.release()


def generate_preview(
        frame_bgr,
        color='#6600CC',
        mode='lab_colorize',
        strength=0.85,
        feather=15,
        std_threshold=35,
        brightness_threshold=185,
        fixed_bounds=None,
        max_preview_size=800,
):
    """
    生成预览图：返回 (原图, 蒙版可视化叠加图, 变色效果图) 三张图片。
    所有返回图片均为 BGR numpy array，已缩放到预览尺寸。

    参数：
      frame_bgr         : 输入帧/图片（BGR numpy array）
      color             : 目标颜色
      mode              : 变色模式
      strength          : 变色强度
      feather           : 边缘羽化
      std_threshold     : 蒙版检测参数
      brightness_threshold: 蒙版检测参数
      fixed_bounds      : 手动蒙版区域 dict(top,bottom,left,right) 或 None
      max_preview_size  : 预览最大边长

    返回：
      (original, mask_overlay, result, bounds_dict_or_None)
    """
    H, W = frame_bgr.shape[:2]

    # 1. 检测或构建蒙版
    if fixed_bounds:
        mask = np.zeros((H, W), dtype=np.uint8)
        t = min(fixed_bounds['top'], H)
        b = min(fixed_bounds['bottom'], H)
        l = min(fixed_bounds['left'], W)
        r = min(fixed_bounds['right'], W)
        mask[t:b, l:r] = 255
        bounds = fixed_bounds
    else:
        mask, bounds = detect_frosted_mask(
            frame_bgr,
            std_threshold=std_threshold,
            brightness_threshold=brightness_threshold,
        )

    if mask is None:
        # 未检测到蒙版，用全图
        mask = np.ones((H, W), dtype=np.uint8) * 255
        bounds = dict(top=0, bottom=H, left=0, right=W)

    # 2. 蒙版可视化叠加（半透明蓝色高亮蒙版区域 + 红色边框）
    mask_overlay = frame_bgr.copy()
    # 蒙版区域用半透明蓝色叠加
    blue_tint = np.zeros_like(frame_bgr)
    blue_tint[:, :] = (255, 180, 50)  # BGR: 淡蓝色
    mask_3ch = cv2.merge([mask, mask, mask])
    alpha_val = 0.3
    mask_region = mask_3ch > 0
    mask_overlay[mask_region] = cv2.addWeighted(
        frame_bgr, 1 - alpha_val, blue_tint, alpha_val, 0
    )[mask_region]
    # 在蒙版边界画红色矩形框
    if bounds:
        cv2.rectangle(
            mask_overlay,
            (bounds['left'], bounds['top']),
            (bounds['right'], bounds['bottom']),
            (0, 0, 255), 3  # 红色, 线宽3
        )
        # 标注蒙版坐标
        label = f"T:{bounds['top']} B:{bounds['bottom']} L:{bounds['left']} R:{bounds['right']}"
        cv2.putText(
            mask_overlay, label,
            (bounds['left'] + 5, max(bounds['top'] - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2
        )

    # 3. 变色效果图
    result = apply_filter_to_mask(
        frame_bgr, mask,
        mode=mode, color=color,
        strength=strength, feather=feather,
    )

    # 4. 缩放到预览尺寸
    scale = min(max_preview_size / W, max_preview_size / H, 1.0)
    if scale < 1.0:
        new_w, new_h = int(W * scale), int(H * scale)
        original_small = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        mask_overlay_small = cv2.resize(mask_overlay, (new_w, new_h), interpolation=cv2.INTER_AREA)
        result_small = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        original_small = frame_bgr.copy()
        mask_overlay_small = mask_overlay
        result_small = result

    return original_small, mask_overlay_small, result_small, bounds


# ══════════════════════════════════════════════════════
#  支持格式定义
# ══════════════════════════════════════════════════════

VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv', '.webm', '.ts'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}


def _is_supported_file(path):
    """检查文件是否为支持的视频或图片格式"""
    ext = os.path.splitext(path)[1].lower()
    return ext in VIDEO_EXTS or ext in IMAGE_EXTS


def _is_video(path):
    """检查文件是否为视频"""
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _is_image(path):
    """检查文件是否为图片"""
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


# ══════════════════════════════════════════════════════
#  QObject Worker（后台线程）
# ══════════════════════════════════════════════════════

class TextRecolorWorker(QObject):
    """视频/图片文字变色后台工作线程"""
    finished = Signal()
    progress = Signal(int, str)           # 百分比, 消息
    file_status = Signal(int, str)        # 文件索引, 状态文本
    file_progress = Signal(int, int)      # 文件索引, 百分比（单文件内部进度）
    error = Signal(str)

    def __init__(self, file_paths, output_dir, color='#6600CC', mode='lab_colorize',
                 strength=0.85, feather=15, std_threshold=35,
                 brightness_threshold=185, fixed_bounds=None,
                 detect_every_n=0):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.color = color
        self.mode = mode
        self.strength = strength
        self.feather = feather
        self.std_threshold = std_threshold
        self.brightness_threshold = brightness_threshold
        self.fixed_bounds = fixed_bounds
        self.detect_every_n = detect_every_n
        self._is_running = True

    def run(self):
        """批量处理所有文件"""
        total = len(self.file_paths)
        for i, file_path in enumerate(self.file_paths):
            if not self._is_running:
                break

            try:
                file_name = os.path.basename(file_path)
                self.file_status.emit(i, "🔄 处理中...")
                self.progress.emit(
                    int((i / total) * 100),
                    f"正在处理: {file_name}..."
                )

                # 构建输出路径
                stem = Path(file_path).stem
                ext = Path(file_path).suffix

                if _is_video(file_path):
                    out_name = f"{stem}_recolor{ext}"
                    out_path = os.path.join(self.output_dir, out_name)

                    def _progress_cb(cur, tot, idx=i):
                        pct = int((cur / tot) * 100) if tot > 0 else 0
                        self.file_progress.emit(idx, pct)

                    process_video(
                        input_path=file_path,
                        output_path=out_path,
                        color=self.color,
                        mode=self.mode,
                        strength=self.strength,
                        feather=self.feather,
                        detect_every_n=self.detect_every_n,
                        fixed_bounds=self.fixed_bounds,
                        std_threshold=self.std_threshold,
                        brightness_threshold=self.brightness_threshold,
                        progress_callback=_progress_cb,
                    )
                elif _is_image(file_path):
                    out_name = f"{stem}_recolor{ext}"
                    out_path = os.path.join(self.output_dir, out_name)

                    process_image(
                        input_path=file_path,
                        output_path=out_path,
                        color=self.color,
                        mode=self.mode,
                        strength=self.strength,
                        feather=self.feather,
                        std_threshold=self.std_threshold,
                        brightness_threshold=self.brightness_threshold,
                        fixed_bounds=self.fixed_bounds,
                    )
                    self.file_progress.emit(i, 100)
                else:
                    self.file_status.emit(i, "⚠️ 不支持的格式")
                    continue

                self.file_status.emit(i, "✅ 完成")

            except Exception as e:
                logger.error(f"处理文件 {file_path} 失败: {e}", exc_info=True)
                self.error.emit(f"处理 {os.path.basename(file_path)} 时出错: {str(e)}")
                self.file_status.emit(i, "❌ 失败")

        self.progress.emit(100, "处理完成")
        self.finished.emit()

    def stop(self):
        """停止处理"""
        self._is_running = False
