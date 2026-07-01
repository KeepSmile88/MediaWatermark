#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shlex
import tempfile
import traceback
import subprocess

from pathlib import Path
from typing import List, Tuple, Optional

from PySide6.QtCore import QThread, Signal, QObject

from video_watermarker_app.utils.config import WatermarkConfig, HistoryManager
from video_watermarker_app.utils.common import (
    to_ffmpeg_filter_path, default_font_path, find_font_path,
    check_ffmpeg,
    is_video_file,
    is_image_file,
    get_available_encoders,
    get_gpu_params,
    analyze_smart_colors,
    calc_auto_font_size,
    get_sp_kwargs
)
from video_watermarker_app.utils.logger import logger


class WatermarkWorker(QThread):
    """
    后台工作线程，负责遍历文件列表并执行 FFmpeg 任务。
    """
    task_started = Signal(int, str)                # idx, filename
    task_progress = Signal(int, float)             # idx, progress(0.0~1.0)
    task_finished = Signal(int, bool, str, str)    # idx, success, out_path, msg
    all_finished = Signal()                        # 全部完成
    log_msg = Signal(str)                          # 日志信息

    def __init__(self, idx: int, file_path: str, config: WatermarkConfig, parent: QObject = None):
        super().__init__(parent)
        self.idx = idx
        self.file_path = file_path
        self.cfg = config
        self.ffmpeg, self.ffprobe = check_ffmpeg()
        self.history = HistoryManager()
        self._stop_flag = False
        self._current_proc: Optional[subprocess.Popen] = None

    def stop(self):
        """请求停止任务"""
        self._stop_flag = True
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
            except Exception:
                pass
        self.log_msg.emit("正在停止任务...")

    def run(self):
        logger.info(f"Task started for: {self.file_path}")
        if not self.ffmpeg or not self.ffprobe:
            self.task_finished.emit(self.idx, False, "", "缺少 FFmpeg/FFprobe")
            return

        file_path = self.file_path
        i = self.idx
        
        self.task_started.emit(i, file_path)
        
        is_video = is_video_file(file_path)
        is_image = is_image_file(file_path)

        if not is_video and not is_image:
            self.task_finished.emit(i, False, "", "不支持的格式")
            return

        # 检查历史记录
        if self.history.is_processed(file_path):
            self.task_finished.emit(i, True, "SKIP", "跳过") 
            return

        try:
            if is_video:
                success, msg = self._process_video(file_path)
            else:
                success, msg = self._process_image(file_path)
            
            if success:
                # --- 原地替换后处理逻辑 ---
                final_path = msg  # 这个 msg 就是 _get_output_path 生成的路径
                if self.cfg.inplace_replace:
                    try:
                        # 确保关闭所有可能的文件句柄（FFmpeg 进程已 wait 退出）
                        # 执行原子替换
                        origin_p = str(file_path)
                        temp_p = msg
                        # Windows 下 os.replace 可能因为权限或占用失败
                        os.replace(temp_p, origin_p)
                        final_path = origin_p
                    except Exception as re_err:
                        success = False
                        msg = f"原地替换失败: {re_err}"
                        logger.error(msg)

                if success:
                    self.history.add_record(file_path)
                    self.task_finished.emit(i, True, final_path, "完成")
                else:
                    self.task_finished.emit(i, False, "", msg)
            else:
                self.task_finished.emit(i, False, "", msg)
        except Exception as e:
            logger.error(f"Error: {e}")
            self.task_finished.emit(i, False, "", str(e))

        logger.info(f"Task finished for: {self.file_path}")

    def _get_output_path(self, in_path: Path) -> Path:
        """根据配置生成输出路径"""
        # 如果是原地替换，我们先输出到一个临时文件
        if self.cfg.inplace_replace:
            # 临时文件名：原文件名 + .inplace_tmp + 后缀
            return in_path.parent / f"{in_path.stem}.inplace_tmp{in_path.suffix}"

        if self.cfg.same_dir:
            out_dir = in_path.parent
        else:
            out_dir = Path(self.cfg.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
        
        if is_video_file(str(in_path)):
            ext = self.cfg.out_ext.lower().lstrip(".") or "mp4"
        else:
            if self.cfg.lossless_image:
                ext = "png"
            else:
                ext = in_path.suffix.lstrip(".").lower()
                if ext not in ["jpg", "jpeg", "png", "bmp", "webp"]:
                    ext = "png"
        
        return out_dir / f"{in_path.stem}_wm.{ext}"

    def _process_video(self, in_path: str) -> Tuple[bool, str]:
        duration = self._get_duration(in_path)
        w, h = self._get_resolution(in_path)
        if not w: return False, "无法获取视频分辨率"
        
        # 构建多水印滤镜图
        all_cfgs = self._collect_all_watermark_cfgs()
        vf, txt_files, image_inputs = self._build_multi_watermark_graph(all_cfgs, w, h)
        if not vf: return False, "滤镜构建失败"
        
        out_p = self._get_output_path(Path(in_path))
        
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(in_path)]
        # 添加所有图片水印输入
        for img_path in image_inputs:
            cmd.extend(["-loop", "1", "-i", str(img_path)])
        
        cmd.extend([
            "-filter_complex", vf,
            "-map", "[v]",
            "-map", "0:a?",
        ])
        
        # 编码参数
        if self.cfg.gpu_enabled:
            encoders = get_available_encoders()
            gpu_params = get_gpu_params(encoders, self.cfg.crf, self.cfg.preset)
            cmd.extend(gpu_params)
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-crf", str(self.cfg.crf),
                "-preset", self.cfg.preset,
            ])
            
        cmd.extend([
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            str(out_p)
        ])
        
        try:
            return self._run_ffmpeg_process(cmd, duration, str(out_p))
        finally:
            for tf in txt_files:
                if tf and os.path.exists(tf):
                    try: os.unlink(tf)
                    except: pass

    def _process_image(self, in_path: str) -> Tuple[bool, str]:
        w, h = self._get_resolution(in_path)
        if not w: return False, "无法获取图片分辨率"
        
        all_cfgs = self._collect_all_watermark_cfgs()
        vf, txt_files, image_inputs = self._build_multi_watermark_graph(all_cfgs, w, h)
        if not vf: return False, "滤镜构建失败"
        
        out_p = self._get_output_path(Path(in_path))
        
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(in_path)]
        for img_path in image_inputs:
            cmd.extend(["-i", str(img_path)])
        
        cmd.extend([
            "-filter_complex", vf,
            "-map", "[v]",
            "-frames:v", "1",
            "-progress", "pipe:1",
            "-nostats",
            str(out_p)
        ])

        try:
            return self._run_ffmpeg_process(cmd, None, str(out_p))
        finally:
            for tf in txt_files:
                if tf and os.path.exists(tf):
                    try: os.unlink(tf)
                    except: pass

    def _collect_all_watermark_cfgs(self):
        """收集主水印 + 额外水印层的配置列表"""
        cfgs = [self.cfg]
        if hasattr(self.cfg, 'extra_watermarks') and self.cfg.extra_watermarks:
            for extra in self.cfg.extra_watermarks:
                if isinstance(extra, WatermarkConfig):
                    cfgs.append(extra)
        return cfgs

    def _calc_avoidance_offsets(self, cfgs, main_w, main_h):
        """
        智能避让：预扫描所有水印图层，估算角落水印的渲染高度。
        当"下中"水印与"右下/左下"共存，或"上中"与"右上/左上"共存时，
        返回需要向内偏移的像素量，避免重叠。

        返回: (bottom_avoid_px, top_avoid_px)
        """
        bottom_heights = []  # 底部角落水印的估算高度
        top_heights = []     # 顶部角落水印的估算高度

        has_bottom_center = any(c.position == "下中" for c in cfgs)
        has_top_center = any(c.position == "上中" for c in cfgs)

        # 如果没有上中/下中水印，无需计算避让
        if not has_bottom_center and not has_top_center:
            return 0, 0

        for cfg in cfgs:
            estimated_h = 0

            if cfg.wm_type == "text" and cfg.text:
                # 文字水印：用字号估算高度（字号 × 1.4 覆盖行高+间距）
                fs = max(1, int(main_h * (cfg.text_size_pct / 100.0)))
                estimated_h = int(fs * 1.4)
            elif cfg.wm_type == "image" and cfg.image_path and os.path.exists(cfg.image_path):
                # 图片水印：根据缩放比估算高度
                wm_w = max(1, int(main_w * (cfg.image_scale_pct / 100.0)))
                try:
                    from PIL import Image
                    with Image.open(cfg.image_path) as img:
                        orig_w, orig_h = img.size
                        if orig_w > 0:
                            estimated_h = int(wm_w * orig_h / orig_w)
                except Exception:
                    # 无法读取图片，用保守估算
                    estimated_h = int(wm_w * 0.5)

            if estimated_h <= 0:
                continue

            # 按位置分类收集
            if cfg.position in ("右下", "左下") and has_bottom_center:
                bottom_heights.append(estimated_h)
            elif cfg.position in ("右上", "左上") and has_top_center:
                top_heights.append(estimated_h)

        # 取最大高度作为避让量，再加一个间距（取 margin 的一半或至少 10px）
        padding = max(10, int(main_h * 0.01))
        bottom_avoid = (max(bottom_heights) + padding) if bottom_heights else 0
        top_avoid = (max(top_heights) + padding) if top_heights else 0

        return bottom_avoid, top_avoid

    def _build_multi_watermark_graph(self, cfgs, main_w, main_h):
        """
        构建多水印链式滤镜图。
        返回: (vf_string, txt_temp_files_list, image_input_paths_list)
        """
        filter_parts = []
        txt_files = []
        image_inputs = []  # 记录需要 -i 输入的图片路径
        input_idx = 1  # 0 是主视频，从 1 开始分配给图片水印
        current_label = "[0:v]"  # 当前视频流标签

        # ---- 智能避让：预扫描所有图层，估算角落水印高度 ----
        bottom_avoid, top_avoid = self._calc_avoidance_offsets(cfgs, main_w, main_h)

        for i, cfg in enumerate(cfgs):
            is_last = (i == len(cfgs) - 1)
            out_label = "[v]" if is_last else f"[v{i}]"

            if cfg.wm_type == "image":
                if not cfg.image_path or not os.path.exists(cfg.image_path):
                    # 跳过无效的图片水印，调整 is_last
                    if is_last and filter_parts:
                        # 需要把上一个滤镜的输出标签改为 [v]
                        filter_parts[-1] = filter_parts[-1].rsplit("[", 1)[0] + "[v]"
                    continue
                
                image_inputs.append(cfg.image_path)
                img_stream = f"[{input_idx}:v]"
                input_idx += 1

                margin = cfg.margin
                wm_w = max(1, int(main_w * (cfg.image_scale_pct / 100.0)))

                # 计算居中 Y 偏移表达式
                cy_offset = cfg.center_y_offset
                if cy_offset >= 0:
                    center_y_expr = f"(main_h-overlay_h)/2+{cy_offset}"
                else:
                    center_y_expr = f"(main_h-overlay_h)/2-{abs(cy_offset)}"

                # 智能避让 + 用户偏移优先级：
                # 用户显式设置了 center_y_offset 时，直接使用用户值（最高优先级）
                # 否则使用自动避让的偏移量
                user_offset = cfg.center_y_offset
                bottom_margin_total = margin
                top_margin_total = margin
                if cfg.position == "下中":
                    extra_y = abs(user_offset) if user_offset != 0 else bottom_avoid
                    bottom_margin_total = margin + extra_y
                    # 用户的偏移方向：正值下移（减少避让），负值上移（增加避让）
                    if user_offset > 0:
                        bottom_margin_total = max(margin, margin + bottom_avoid - user_offset)
                elif cfg.position == "上中":
                    extra_y = abs(user_offset) if user_offset != 0 else top_avoid
                    top_margin_total = margin + extra_y
                    if user_offset < 0:
                        top_margin_total = max(margin, margin + top_avoid + user_offset)

                pos_map = {
                    "左上": (f"{margin}", f"{margin}"),
                    "右上": (f"main_w-overlay_w-{margin}", f"{margin}"),
                    "左下": (f"{margin}", f"main_h-overlay_h-{margin}"),
                    "右下": (f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"),
                    "上中": ("(main_w-overlay_w)/2", f"{top_margin_total}"),
                    "下中": ("(main_w-overlay_w)/2", f"main_h-overlay_h-{bottom_margin_total}"),
                    "居中": ("(main_w-overlay_w)/2", center_y_expr),
                }
                x, y = pos_map.get(cfg.position, (str(cfg.custom_x), str(cfg.custom_y)))

                feather = ""
                if cfg.feather_radius > 0:
                    rad = cfg.feather_radius
                    feather = f",boxblur={rad}:1:{rad}:1:{rad}:1"

                wm_label = f"[wm{i}]"
                part = (
                    f"{img_stream}format=rgba,scale={wm_w}:-1,"
                    f"colorchannelmixer=aa={cfg.opacity:.2f}{feather}{wm_label};"
                    f"{current_label}{wm_label}overlay=x={x}:y={y}:shortest=1{out_label}"
                )
                filter_parts.append(part)
                current_label = out_label

            elif cfg.wm_type == "text":
                if not cfg.text:
                    if is_last and filter_parts:
                        filter_parts[-1] = filter_parts[-1].rsplit("[", 1)[0] + "[v]"
                    continue

                try:
                    fd, txt_path = tempfile.mkstemp(suffix=".txt")
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(cfg.text)
                    txt_files.append(txt_path)
                except Exception as e:
                    logger.error(f"Failed to create temp text file: {e}")
                    continue

                margin = cfg.margin
                alpha = cfg.opacity
                
                # 上中/下中位置：自动根据画面宽度和文字长度计算字号
                if cfg.position in ("上中", "下中"):
                    fs = calc_auto_font_size(cfg.text, main_w, main_h, margin, cfg.font_name)
                else:
                    fs = max(1, int(main_h * (cfg.text_size_pct / 100.0)))
                
                fontfile = find_font_path(cfg.font_name)

                # 计算居中 Y 偏移表达式
                cy_offset = cfg.center_y_offset
                if cy_offset >= 0:
                    center_y_expr_txt = f"(h-text_h)/2+{cy_offset}"
                else:
                    center_y_expr_txt = f"(h-text_h)/2-{abs(cy_offset)}"

                # 智能避让 + 用户偏移优先级：
                user_offset = cfg.center_y_offset
                bottom_margin_total = margin
                top_margin_total = margin
                if cfg.position == "下中":
                    extra_y = abs(user_offset) if user_offset != 0 else bottom_avoid
                    bottom_margin_total = margin + extra_y
                    if user_offset > 0:
                        bottom_margin_total = max(margin, margin + bottom_avoid - user_offset)
                elif cfg.position == "上中":
                    extra_y = abs(user_offset) if user_offset != 0 else top_avoid
                    top_margin_total = margin + extra_y
                    if user_offset < 0:
                        top_margin_total = max(margin, margin + top_avoid + user_offset)

                pos_map = {
                    "左上": (f"{margin}", f"{margin}"),
                    "右上": (f"w-text_w-{margin}", f"{margin}"),
                    "左下": (f"{margin}", f"h-text_h-{margin}"),
                    "右下": (f"w-text_w-{margin}", f"h-text_h-{margin}"),
                    "上中": ("(w-text_w)/2", f"{top_margin_total}"),
                    "下中": ("(w-text_w)/2", f"h-text_h-{bottom_margin_total}"),
                    "居中": ("(w-text_w)/2", center_y_expr_txt),
                }
                x_expr, y_expr = pos_map.get(cfg.position, (str(cfg.custom_x), str(cfg.custom_y)))

                # 智能选色：所有启用 auto_color 的文字水印层都生效
                font_color = cfg.font_color or "#FFFFFF"
                border_color = cfg.border_color or "#000000"
                border_w = 0

                if cfg.auto_color:
                    try:
                        sample_img = None
                        is_temp = False
                        if is_image_file(self.file_path):
                            sample_img = self.file_path
                        else:
                            fd2, tmp_p = tempfile.mkstemp(suffix=".jpg")
                            os.close(fd2)
                            try:
                                cmd_sample = [
                                    self.ffmpeg, "-y", "-hide_banner", "-i", self.file_path,
                                    "-vf", "select=eq(n\\\\,4)", "-frames:v", "1", "-v", "error", tmp_p
                                ]
                                subprocess.run(cmd_sample, timeout=10, **get_sp_kwargs())
                                if os.path.exists(tmp_p) and os.path.getsize(tmp_p) > 0:
                                    sample_img = tmp_p
                                    is_temp = True
                            except Exception as run_e:
                                logger.error(f"Sampling run failed: {run_e}")

                        if sample_img:
                            est_w, est_h = int(main_w * 0.3), int(main_h * 0.1)
                            def eval_pos(p_str, mw, mh):
                                if "main_w" in p_str or "w" in p_str:
                                    p_str = p_str.replace("main_w", str(mw)).replace("w", str(mw)).replace("text_w", "100")
                                if "main_h" in p_str or "h" in p_str:
                                    p_str = p_str.replace("main_h", str(mh)).replace("h", str(mh)).replace("text_h", "30")
                                try:
                                    return int(eval(p_str, {"__builtins__": None}, {}))
                                except:
                                    return 0
                            sx = eval_pos(x_expr, main_w, main_h)
                            sy = eval_pos(y_expr, main_w, main_h)
                            f_col, b_col = analyze_smart_colors(sample_img, sx, sy, est_w, est_h)
                            font_color = f_col
                            border_color = b_col
                            border_w = 2

                    except Exception as e:
                        logger.error(f"Sampling failed: {e}")
                    finally:
                        if is_temp and sample_img and os.path.exists(sample_img):
                            os.unlink(sample_img)

                # 构建 drawtext 滤镜参数
                parts = []
                if fontfile and os.path.exists(fontfile):
                    parts.append(f"fontfile='{to_ffmpeg_filter_path(fontfile)}'")
                parts.append(f"textfile='{to_ffmpeg_filter_path(txt_path)}'")
                parts.append("reload=1")
                parts.append(f"fontsize={fs}")

                hex_color = font_color.replace("#", "0x")
                parts.append(f"fontcolor={hex_color}@{alpha:.2f}")

                if border_w > 0:
                    parts.append(f"borderw={border_w}")
                    parts.append(f"bordercolor={border_color.replace('#', '0x')}")

                parts.append(f"x={x_expr}")
                parts.append(f"y={y_expr}")

                # 背景色支持
                if cfg.bg_enabled and cfg.bg_color:
                    bg_hex = cfg.bg_color.replace('#', '0x')
                    parts.append(f"box=1")
                    parts.append(f"boxcolor={bg_hex}@{alpha:.2f}")
                    parts.append(f"boxborderw=8")

                if border_w == 0 and not (cfg.bg_enabled and cfg.bg_color):
                    parts.append("shadowcolor=black@0.35")
                    parts.append("shadowx=2")
                    parts.append("shadowy=2")

                part = f"{current_label}drawtext={':'.join(parts)}{out_label}"
                filter_parts.append(part)
                current_label = out_label

        if not filter_parts:
            return None, txt_files, image_inputs

        vf = ";".join(filter_parts)
        return vf, txt_files, image_inputs

    def _run_ffmpeg_process(self, cmd: List[str], duration: Optional[float], out_path: str) -> Tuple[bool, str]:
        # logger.info(f"Exec: {' '.join(shlex.quote(s) for s in cmd)}")

        try:
            kwargs = get_sp_kwargs()
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE
            kwargs['text'] = True
            kwargs['encoding'] = 'utf-8'
            kwargs['errors'] = 'replace'
            
            self._current_proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            return False, f"启动 FFmpeg 失败: {e}"

        proc = self._current_proc
        err_lines = []
        
        while True:
            if self._stop_flag:
                proc.terminate()
                return False, "已取消"
            
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            
            line = line.strip()
            if "=" in line:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    k, v = parts[0].strip(), parts[1].strip()
                    if k in ("out_time_ms", "out_time_us") and duration:
                        try:
                            t = float(v) / 1_000_000.0
                            p = min(1.0, max(0.01, t / duration))
                            self.task_progress.emit(self.idx, p)
                        except: pass
                    if k == "progress" and v == "end":
                        self.task_progress.emit(self.idx, 1.0)

        ret = proc.wait()
        self._current_proc = None
        
        if ret == 0:
            return True, str(out_path)
        else:
            try:
                remaining_stderr = proc.stderr.read()
                if remaining_stderr:
                    err_lines.extend(remaining_stderr.splitlines())
            except:
                pass

            # 记录完整错误到日志文件
            full_error_log = "\n".join(err_lines)
            logger.error(
                f"FFmpeg failed with exit code {ret}.\nFile: {self.file_path}\nFull Stderr summary:\n{full_error_log}")

            # 提取对用户有意义的报错提示
            important_msg = []
            for l in reversed(err_lines):
                l_s = l.strip()
                if not l_s: continue
                # 优先提取带 Error/Failed 的行
                if any(x in l_s.lower() for x in ["error", "invalid", "failed", "could not", "no such"]):
                    important_msg.insert(0, l_s)
                if len(important_msg) >= 5: break

            if not important_msg:
                # 如果没找到关键字，取最后 3 条有效内容
                important_msg = [l.strip() for l in err_lines if l.strip()][-3:]

            error_summary = "\n".join(important_msg) if important_msg else f"FFmpeg 任务失败，退出码: {ret}"
            return False, error_summary

    def _get_duration(self, path: str) -> Optional[float]:
        try:
            cmd = [self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
            out = subprocess.check_output(cmd, text=True, errors='replace', **get_sp_kwargs()).strip()
            return float(out)
        except: return None

    def _get_resolution(self, path: str) -> Tuple[Optional[int], Optional[int]]:
        try:
            cmd = [self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)]
            out = subprocess.check_output(cmd, text=True, errors='replace', **get_sp_kwargs()).strip()
            if "x" in out:
                w, h = out.split("x", 1)
                return int(w), int(h)
        except Exception as e:
            logger.error(f"get resolution falid: {traceback.format_exc(e)}")
        return None, None
