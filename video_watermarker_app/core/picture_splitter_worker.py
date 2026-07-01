#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
图片分割核心工作线程模块。
将 picture_splitter.py 的算法逻辑封装为 QObject Worker，
支持批量分割、信号回报进度与状态。
"""

import os
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Signal

from video_watermarker_app.utils.logger import logger


# ══════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════

def smooth(arr, w=5):
    """一维平滑滤波"""
    return np.convolve(arr, np.ones(w) / w, mode='same')

def normalize(arr):
    """归一化到 [0, 1]"""
    lo, hi = arr.min(), arr.max()
    return (arr - lo) / (hi - lo + 1e-9)


# ══════════════════════════════════════════════════════
#  图片类型检测 & 自适应权重
# ══════════════════════════════════════════════════════

def detect_image_type(arr_gray, arr_rgb=None):
    """
    检测图片类型，返回 (img_type, weights)。
    weights 包含6路信号：grad/color/dip/dark/white/color_line
    """
    H, W = arr_gray.shape
    row_proj = arr_gray.mean(axis=1).astype(float)
    col_proj = arr_gray.mean(axis=0).astype(float)

    mean_brightness = arr_gray.mean()
    dark_ratio  = (arr_gray < 30).mean()
    white_ratio = (arr_gray > 225).mean()

    dark_rows  = (row_proj < mean_brightness * 0.4).sum()
    dark_cols  = (col_proj < mean_brightness * 0.4).sum()
    white_rows = (row_proj > mean_brightness * 1.6).sum()
    white_cols = (col_proj > mean_brightness * 1.6).sum()

    has_dark_grid  = (dark_rows  >= 2 or dark_cols  >= 2) and dark_ratio  > 0.005
    has_white_grid = (white_rows >= 2 or white_cols >= 2) and white_ratio > 0.005

    # 彩色边框线检测
    has_color_border = False
    if arr_rgb is not None:
        row_var = arr_rgb.astype(float).std(axis=1).mean(axis=1)  # H
        col_var = arr_rgb.astype(float).std(axis=0).mean(axis=1)  # W
        very_uniform_rows = (row_var < row_var.mean() * 0.3).sum()
        very_uniform_cols = (col_var < col_var.mean() * 0.3).sum()
        has_color_border = (very_uniform_rows >= 2 or very_uniform_cols >= 2)

    if has_color_border:
        weights = dict(grad=0.10, color=0.10, dip=0.05, dark=0.05, white=0.05, color_line=0.65)
        img_type = "color_border"
    elif has_dark_grid:
        weights = dict(grad=0.20, color=0.15, dip=0.10, dark=0.45, white=0.05, color_line=0.05)
        img_type = "dark_grid"
    elif has_white_grid:
        weights = dict(grad=0.20, color=0.15, dip=0.10, dark=0.05, white=0.45, color_line=0.05)
        img_type = "white_grid"
    else:
        weights = dict(grad=0.35, color=0.28, dip=0.17, dark=0.10, white=0.05, color_line=0.05)
        img_type = "content_boundary"

    return img_type, weights


# ══════════════════════════════════════════════════════
#  分割线宽度检测
# ══════════════════════════════════════════════════════

def detect_line_width(proj, split_pos, search_radius=40, threshold_ratio=0.5):
    """
    在 split_pos 附近检测分割线的实际宽度。
    返回 (line_start, line_end)。
    """
    s = smooth(proj.astype(float), 3)
    n = len(s)
    mean_val = s.mean()

    lo = max(0, split_pos - search_radius)
    hi = min(n, split_pos + search_radius)

    center_val = s[min(split_pos, n-1)]
    is_dark  = center_val < mean_val * threshold_ratio
    is_white = center_val > mean_val * (2.0 - threshold_ratio)

    if not (is_dark or is_white):
        return split_pos, split_pos

    if is_dark:
        threshold = mean_val * threshold_ratio
        def in_line(v): return v < threshold
    else:
        threshold = mean_val * (2.0 - threshold_ratio)
        def in_line(v): return v > threshold

    left = split_pos
    while left > lo and in_line(s[left - 1]):
        left -= 1

    right = split_pos
    while right < hi - 1 and in_line(s[right + 1]):
        right += 1

    return left, right


# ══════════════════════════════════════════════════════
#  信号提取（6 路）
# ══════════════════════════════════════════════════════

def sig_dark_valley(proj):
    s = smooth(proj, 3).astype(float)
    score = 1.0 - normalize(s)
    threshold = s.mean() * 0.4
    score[s > threshold] = 0
    return score

def sig_white_valley(proj):
    s = smooth(proj, 3).astype(float)
    score = normalize(s)
    threshold = s.mean() * 1.6
    score[s < threshold] = 0
    return score

def sig_gradient(proj):
    s = smooth(proj.astype(float), 5)
    grad = np.abs(np.diff(s, prepend=s[0]))
    return normalize(smooth(grad, 15))

def sig_local_dip(proj, win_ratio=0.12):
    s = smooth(proj.astype(float), 5)
    n = len(s)
    hw = max(int(n * win_ratio), 20)
    score = np.zeros(n)
    for i in range(hw, n - hw):
        local_mean = s[max(0, i-hw):i+hw].mean()
        score[i] = max(0, local_mean - s[i])
    return normalize(score)

def sig_color_jump(arr_rgb, axis):
    if axis == 0:
        line_colors = arr_rgb.mean(axis=1).astype(float)
    else:
        line_colors = arr_rgb.mean(axis=0).astype(float)
    diff = np.abs(np.diff(line_colors, axis=0, prepend=line_colors[:1]))
    cd = diff.sum(axis=-1)
    return normalize(smooth(cd, 10))

def sig_color_line(arr_rgb, axis):
    """
    检测单色细线（彩色边框线）。
    原理：真正的分割线在整行/列上颜色高度一致（标准差极低），
         同时与相邻行/列的颜色差异大。
    得分 = 颜色一致性 × 与相邻行色差
    """
    rgb = arr_rgb.astype(float)
    if axis == 0:
        row_std = rgb.std(axis=1).mean(axis=1)
        consistency = 1.0 - normalize(smooth(row_std, 3))
        mean_colors = rgb.mean(axis=1)
        diff = np.abs(np.diff(mean_colors, axis=0, prepend=mean_colors[:1])).sum(axis=1)
        difference = normalize(smooth(diff, 5))
    else:
        col_std = rgb.std(axis=0).mean(axis=1)
        consistency = 1.0 - normalize(smooth(col_std, 3))
        mean_colors = rgb.mean(axis=0)
        diff = np.abs(np.diff(mean_colors, axis=0, prepend=mean_colors[:1])).sum(axis=1)
        difference = normalize(smooth(diff, 5))

    return normalize(consistency * difference)


# ══════════════════════════════════════════════════════
#  候选点提取
# ══════════════════════════════════════════════════════

def pick_peaks(score, n, min_spacing, margin):
    s = score.copy()
    s[:margin] = 0
    s[-margin:] = 0
    chosen = []
    for _ in range(n):
        idx = int(np.argmax(s))
        if s[idx] < 1e-6:
            break
        chosen.append((idx, float(score[idx])))
        lo = max(0, idx - min_spacing)
        hi = min(len(s), idx + min_spacing)
        s[lo:hi] = 0
    return chosen


# ══════════════════════════════════════════════════════
#  等分方案工具
# ══════════════════════════════════════════════════════

def score_equal_split(proj, positions, half_win=15):
    s = smooth(proj.astype(float), 5)
    scores = []
    for p in positions:
        lo = max(0, p - half_win)
        hi = min(len(s), p + half_win)
        window = s[lo:hi]
        if len(window) == 0:
            scores.append(0.0)
            continue
        local_min = window.min()
        global_mean = s.mean()
        dark_score = max(0, (global_mean - local_min) / (global_mean + 1e-9))
        scores.append(min(1.0, dark_score * 2))
    return float(np.mean(scores)) if scores else 0.0

def snap_to_signal(pos, score, snap_radius=20):
    lo = max(0, pos - snap_radius)
    hi = min(len(score), pos + snap_radius)
    window = score[lo:hi]
    if window.max() < 1e-3:
        return pos
    return lo + int(np.argmax(window))


# ══════════════════════════════════════════════════════
#  行高均衡校验
# ══════════════════════════════════════════════════════

def check_balance(positions, total_length, n_splits, tolerance=0.20):
    """
    检查分割后各段是否均衡。
    若最大段与最小段之差超过 tolerance × 平均值，返回 False。
    """
    bounds = [0] + list(positions) + [total_length]
    sizes = [bounds[i+1] - bounds[i] for i in range(n_splits + 1)]
    mean_size = np.mean(sizes)
    max_diff = max(sizes) - min(sizes)
    return max_diff <= tolerance * mean_size, sizes


# ══════════════════════════════════════════════════════
#  核心：自适应分割点查找
# ══════════════════════════════════════════════════════

def find_splits(arr_gray, arr_rgb, axis, n=2, verbose=False, weights=None):
    """
    查找 n 个分割点，五级策略：
      A. 强绝对信号（黑/白/彩色分割线）
      B. 尺寸整除 → 等分 + 信号 snap 修正
      C. 多信号融合投票（动态权重，阈值0.35）
      D. 均衡等分回退
      E. 强制等分（兜底）
    """
    if weights is None:
        weights = dict(grad=0.35, color=0.28, dip=0.17, dark=0.10, white=0.05, color_line=0.05)

    length      = arr_gray.shape[0] if axis == 0 else arr_gray.shape[1]
    proj        = (arr_gray.mean(axis=1) if axis == 0 else arr_gray.mean(axis=0)).astype(float)
    min_spacing = max(int(length * 0.15), 30)
    margin      = max(int(length * 0.04), 15)

    # 6 路信号
    s_dark       = sig_dark_valley(proj)
    s_white      = sig_white_valley(proj)
    s_grad       = sig_gradient(proj)
    s_dip        = sig_local_dip(proj)
    s_color      = sig_color_jump(arr_rgb, axis)
    s_color_line = sig_color_line(arr_rgb, axis)

    equal_pos = [length * (i + 1) // (n + 1) for i in range(n)]

    # 策略 A：强绝对信号
    for sig, label in [
        (s_dark,       "黑色分割线"),
        (s_white,      "白色分割线"),
        (s_color_line, "彩色边框线"),
    ]:
        if sig.max() > 0.6:
            peaks = pick_peaks(sig, n, min_spacing, margin)
            if len(peaks) == n:
                positions = sorted([p for p, _ in peaks])
                conf = float(np.mean([v for _, v in peaks]))
                ok, sizes = check_balance(positions, length, n)
                if not ok:
                    continue
                return positions, conf, f"A:{label}"

    # 融合信号（动态权重）
    fused = normalize(
        weights.get('grad', 0)       * s_grad  +
        weights.get('color', 0)      * s_color +
        weights.get('dip', 0)        * s_dip   +
        weights.get('dark', 0)       * s_dark  +
        weights.get('white', 0)      * s_white +
        weights.get('color_line', 0) * s_color_line
    )

    divisible = (length % (n + 1) == 0)

    # 策略 B：尺寸整除
    if divisible:
        snapped = [snap_to_signal(p, fused, snap_radius=25) for p in equal_pos]
        valid = True
        for i in range(len(snapped)):
            for j in range(i+1, len(snapped)):
                if abs(snapped[i] - snapped[j]) < min_spacing // 2:
                    valid = False
                    break
        if valid and snapped != equal_pos:
            ok, _ = check_balance(snapped, length, n)
            if ok:
                conf = max(0.5, float(np.mean([fused[p] for p in snapped])))
                return sorted(snapped), conf, "B:整除+snap"

        eq_conf = max(0.4, score_equal_split(proj, equal_pos))
        return equal_pos, eq_conf, "B:整除等分"

    # 策略 C：多信号融合
    peaks = pick_peaks(fused, n, min_spacing, margin)
    if len(peaks) == n:
        positions = sorted([p for p, _ in peaks])
        conf = float(np.mean([fused[p] for p in positions]))
        ok, sizes = check_balance(positions, length, n)

        if conf > 0.35 and ok:
            return positions, conf, "C:多信号融合"

        eq_conf = score_equal_split(proj, equal_pos)
        return equal_pos, eq_conf, "C→等分"

    # 策略 D：纯等分回退
    return equal_pos, 0.0, "D:等分回退"


# ══════════════════════════════════════════════════════
#  主分割函数
# ══════════════════════════════════════════════════════

def split_image(image_path, rows=3, cols=3, output_dir="output",
                manual_row_splits=None,
                manual_col_splits=None,
                strip_border=0,
                skip_split_line=True):
    """
    分割大图为 rows×cols 子图。

    参数：
        image_path        : 输入图片路径
        rows, cols        : 行列数（默认 3×3）
        output_dir        : 输出目录
        manual_row_splits : 手动行分割坐标 [y1, y2]，覆盖自动检测
        manual_col_splits : 手动列分割坐标 [x1, x2]，覆盖自动检测
        strip_border      : 裁切后每边再向内缩 N 像素（去除残留线条）
        skip_split_line   : True=自动检测分割线宽度，将线像素各半分给相邻两图

    返回：
        (saved_paths, preview_path, info_dict)
    """
    os.makedirs(output_dir, exist_ok=True)

    img      = Image.open(image_path).convert("RGB")
    arr_rgb  = np.array(img)
    arr_gray = np.array(img.convert("L"))
    H, W     = arr_gray.shape

    # 检测图片类型
    img_type, weights = detect_image_type(arr_gray, arr_rgb)

    # 行分割
    if manual_row_splits:
        row_splits, row_conf, row_method = list(manual_row_splits), 1.0, "手动"
    else:
        row_splits, row_conf, row_method = find_splits(
            arr_gray, arr_rgb, axis=0, n=rows-1, weights=weights)

    # 列分割
    if manual_col_splits:
        col_splits, col_conf, col_method = list(manual_col_splits), 1.0, "手动"
    else:
        col_splits, col_conf, col_method = find_splits(
            arr_gray, arr_rgb, axis=1, n=cols-1, weights=weights)

    # 构建边界（考虑分割线宽度）
    row_proj = arr_gray.mean(axis=1).astype(float)
    col_proj = arr_gray.mean(axis=0).astype(float)

    raw_row_bounds = [0] + list(row_splits) + [H]
    raw_col_bounds = [0] + list(col_splits) + [W]

    if skip_split_line:
        adjusted_row_tops    = [0]
        adjusted_row_bottoms = []
        for sp in row_splits:
            line_start, line_end = detect_line_width(row_proj, sp)
            width = line_end - line_start + 1
            half  = width // 2
            adjusted_row_bottoms.append(line_start + half)
            adjusted_row_tops.append(line_start + half)
        adjusted_row_bottoms.append(H)
        row_ranges = list(zip(adjusted_row_tops, adjusted_row_bottoms))

        adjusted_col_tops    = [0]
        adjusted_col_bottoms = []
        for sp in col_splits:
            line_start, line_end = detect_line_width(col_proj, sp)
            width = line_end - line_start + 1
            half  = width // 2
            adjusted_col_bottoms.append(line_start + half)
            adjusted_col_tops.append(line_start + half)
        adjusted_col_bottoms.append(W)
        col_ranges = list(zip(adjusted_col_tops, adjusted_col_bottoms))
    else:
        row_ranges = [(raw_row_bounds[i], raw_row_bounds[i+1]) for i in range(rows)]
        col_ranges = [(raw_col_bounds[i], raw_col_bounds[i+1]) for i in range(cols)]

    # 裁切保存
    saved = []
    for r in range(rows):
        for c in range(cols):
            top,  bottom = row_ranges[r]
            left, right  = col_ranges[c]

            top    = min(top    + strip_border, bottom)
            bottom = max(bottom - strip_border, top)
            left   = min(left   + strip_border, right)
            right  = max(right  - strip_border, left)

            cell = img.crop((left, top, right, bottom))
            num = r * cols + c + 1
            out_path = os.path.join(output_dir, f"{num}.png")
            cell.save(out_path)
            saved.append(out_path)

    # 生成预览图
    preview_path = _save_preview(img, raw_row_bounds, raw_col_bounds, output_dir)

    # 构建信息字典
    info = {
        "image_size": f"{W}×{H}",
        "img_type": img_type,
        "row_conf": row_conf,
        "row_method": row_method,
        "col_conf": col_conf,
        "col_method": col_method,
        "row_heights": [r[1]-r[0] for r in row_ranges],
        "col_widths": [c[1]-c[0] for c in col_ranges],
    }

    return saved, preview_path, info


# ══════════════════════════════════════════════════════
#  预览图
# ══════════════════════════════════════════════════════

def _save_preview(img, row_bounds, col_bounds, output_dir):
    """生成分割预览图，返回预览图路径"""
    W, H = img.size
    preview = img.copy()
    draw = ImageDraw.Draw(preview)

    rows = len(row_bounds) - 1
    cols = len(col_bounds) - 1

    for y in row_bounds[1:-1]:
        draw.line([(0, y), (W, y)], fill=(255, 50, 50), width=4)
    for x in col_bounds[1:-1]:
        draw.line([(x, 0), (x, H)], fill=(50, 100, 255), width=4)

    for r in range(rows):
        for c in range(cols):
            cx = (col_bounds[c] + col_bounds[c+1]) // 2
            cy = (row_bounds[r] + row_bounds[r+1]) // 2
            draw.ellipse([cx-18, cy-18, cx+18, cy+18], fill=(255, 255, 255))
            draw.text((cx-6, cy-8), str(r*cols+c+1), fill=(30, 30, 30))

    max_size = 1400
    scale = min(max_size/W, max_size/H)
    if scale < 1:
        preview = preview.resize((int(W*scale), int(H*scale)), Image.LANCZOS)

    path = os.path.join(output_dir, "preview_grid.png")
    preview.save(path)
    return path


# ══════════════════════════════════════════════════════
#  QObject Worker（后台线程）
# ══════════════════════════════════════════════════════

class PictureSplitterWorker(QObject):
    """图片分割后台工作线程"""
    finished = Signal()
    progress = Signal(int, str)       # 百分比, 消息
    file_status = Signal(int, str)    # 文件索引, 状态文本
    file_result = Signal(int, list, str, dict)  # 文件索引, 保存路径列表, 预览图路径, 信息字典
    error = Signal(str)

    def __init__(self, file_paths, output_dir, rows=3, cols=3,
                 strip_border=0, skip_split_line=True):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.rows = rows
        self.cols = cols
        self.strip_border = strip_border
        self.skip_split_line = skip_split_line
        self._is_running = True

    def run(self):
        """批量处理所有图片"""
        total = len(self.file_paths)
        for i, img_path in enumerate(self.file_paths):
            if not self._is_running:
                break

            try:
                img_name = os.path.splitext(os.path.basename(img_path))[0]
                self.file_status.emit(i, "🔍 分析中...")
                self.progress.emit(int((i / total) * 100),
                                   f"正在处理: {img_name}...")

                # 每张图片建立独立子目录
                sub_dir = os.path.join(self.output_dir, img_name)

                saved, preview_path, info = split_image(
                    image_path=img_path,
                    rows=self.rows,
                    cols=self.cols,
                    output_dir=sub_dir,
                    strip_border=self.strip_border,
                    skip_split_line=self.skip_split_line
                )

                cell_count = len(saved)
                self.file_status.emit(i, f"✅ 完成 ({cell_count}张子图)")
                self.file_result.emit(i, saved, preview_path, info)

            except Exception as e:
                logger.error(f"处理图片 {img_path} 失败: {e}", exc_info=True)
                self.error.emit(f"处理 {os.path.basename(img_path)} 时出错: {str(e)}")
                self.file_status.emit(i, "❌ 失败")

        self.progress.emit(100, "处理完成")
        self.finished.emit()

    def stop(self):
        """停止处理"""
        self._is_running = False
