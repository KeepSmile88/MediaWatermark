#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import sys
import tempfile
import shlex
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
    analyze_smart_colors
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

        if self.history.is_processed(file_path):
            self.task_finished.emit(i, True, "SKIP", "跳过") 
            return

        try:
            if is_video:
                success, msg = self._process_video(file_path)
            else:
                success, msg = self._process_image(file_path)
            
            if success:
                final_path = msg
                if self.cfg.inplace_replace:
                    try:
                        origin_p = str(file_path)
                        temp_p = msg
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
            ext = in_path.suffix.lstrip(".").lower()
            if ext not in ["jpg", "jpeg", "png", "bmp", "webp"]:
                ext = "png"
        
        return out_dir / f"{in_path.stem}_wm.{ext}"

    def _process_video(self, in_path: str) -> Tuple[bool, str]:
        duration = self._get_duration(in_path)
        w, h = self._get_resolution(in_path)
        if not w: return False, "无法获取视频分辨率"
        
        vf, txt_file = self._prepare_filter_graph(w, h)
        if not vf: return False, "滤镜构建失败"
        
        out_p = self._get_output_path(Path(in_path))
        
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(in_path)]
        if self.cfg.wm_type == "image":
             cmd.extend(["-loop", "1", "-i", str(self.cfg.image_path)])
        
        cmd.extend([
            "-filter_complex", vf,
            "-map", "[v]",
            "-map", "0:a?",
        ])

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
            if txt_file and os.path.exists(txt_file):
                try: os.unlink(txt_file)
                except: pass

    def _process_image(self, in_path: str) -> Tuple[bool, str]:
        w, h = self._get_resolution(in_path)
        if not w: return False, "无法获取图片分辨率"
        
        vf, txt_file = self._prepare_filter_graph(w, h)
        if not vf: return False, "滤镜构建失败"
        
        out_p = self._get_output_path(Path(in_path))
        
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostdin", "-i", str(in_path)]
        if self.cfg.wm_type == "image":
             cmd.extend(["-i", str(self.cfg.image_path)])
        
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
            if txt_file and os.path.exists(txt_file):
                try: os.unlink(txt_file)
                except: pass

    def _prepare_filter_graph(self, main_w: int, main_h: int) -> Tuple[Optional[str], Optional[str]]:
        """构建滤镜图。返回 (vf_string, txt_temp_file)"""
        margin = self.cfg.margin
        alpha = self.cfg.opacity

        if self.cfg.wm_type == "image":
            if not self.cfg.image_path or not os.path.exists(self.cfg.image_path):
                return None, None
            
            wm_w = max(1, int(main_w * (self.cfg.image_scale_pct / 100.0)))
            
            def get_img_pos(pos):
                if pos == "左上": return (f"{margin}", f"{margin}")
                if pos == "右上": return (f"main_w-overlay_w-{margin}", f"{margin}")
                if pos == "左下": return (f"{margin}", f"main_h-overlay_h-{margin}")
                if pos == "右下": return (f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}")
                if pos == "居中": return (f"(main_w-overlay_w)/2", f"(main_h-overlay_h)/2")
                return (str(self.cfg.custom_x), str(self.cfg.custom_y))

            x, y = get_img_pos(self.cfg.position)
            overlay_pos = f"x={x}:y={y}"

            wm_path = to_ffmpeg_filter_path(self.cfg.image_path)
            feather_filter = ""
            if self.cfg.feather_radius > 0:
                rad = self.cfg.feather_radius
                feather_filter = f",boxblur={rad}:1:{rad}:1:{rad}:1"
            
            vf = (
                f"[1:v]format=rgba,scale={wm_w}:-1,"
                f"colorchannelmixer=aa={self.cfg.opacity:.2f}{feather_filter}[wm];"
                f"[0:v][wm]overlay={overlay_pos}:shortest=1[v]"
            )
            return vf, None

        else:
            if not self.cfg.text: return None, None
            
            try:
                fd, txt_path = tempfile.mkstemp(suffix=".txt")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(self.cfg.text)
            except Exception as e:
                logger.error(f"Failed to create temp text file: {e}")
                return None, None
            
            fs = max(1, int(main_h * (self.cfg.text_size_pct / 100.0)))
            fontfile = find_font_path(self.cfg.font_name)
            
            def get_txt_pos(pos):
                 if pos == "左上": return (f"{margin}", f"{margin}")
                 if pos == "右上": return (f"w-text_w-{margin}", f"{margin}")
                 if pos == "左下": return (f"{margin}", f"h-text_h-{margin}")
                 if pos == "右下": return (f"w-text_w-{margin}", f"h-text_h-{margin}")
                 if pos == "居中": return (f"(w-text_w)/2", f"(h-text_h)/2")
                 return (str(self.cfg.custom_x), str(self.cfg.custom_y))

            x_expr, y_expr = get_txt_pos(self.cfg.position)

            font_color = self.cfg.font_color or "#FFFFFF"
            border_color = self.cfg.border_color or "#000000"
            border_w = 0

            if self.cfg.auto_color:
                try:
                    sample_img = None
                    is_temp = False
                    if is_image_file(self.file_path):
                        sample_img = self.file_path
                    else:
                        fd, tmp_p = tempfile.mkstemp(suffix=".jpg")
                        os.close(fd)
                        cmd_sample = [
                            self.ffmpeg, "-y", "-hide_banner", "-i", self.file_path,
                            "-vf", "select=eq(n\\,4)", "-frames:v", "1", "-v", "error", tmp_p
                        ]
                        subprocess.run(cmd_sample, shell=True, timeout=10)
                        if os.path.exists(tmp_p) and os.path.getsize(tmp_p) > 0:
                            sample_img = tmp_p
                            is_temp = True
                    
                    if sample_img:
                        est_w, est_h = int(main_w * 0.3), int(main_h * 0.1)

                        def eval_pos(p_str, main_val, wm_val):
                            if "main_w" in p_str or "w" in p_str:
                                p_str = p_str.replace("main_w", str(main_w)).replace("w", str(main_w)).replace("text_w", "100")
                            if "main_h" in p_str or "h" in p_str:
                                p_str = p_str.replace("main_h", str(main_h)).replace("h", str(main_h)).replace("text_h", "30")
                            try:
                                return int(eval(p_str, {"__builtins__":None}, {}))
                            except: return 0

                        sx = eval_pos(x_expr, main_w, 100)
                        sy = eval_pos(y_expr, main_h, 30)
                        
                        f_col, b_col = analyze_smart_colors(sample_img, sx, sy, est_w, est_h)
                        font_color = f_col
                        border_color = b_col
                        border_w = 2 
                        
                    if is_temp and sample_img and os.path.exists(sample_img):
                        os.unlink(sample_img)
                except Exception as e:
                    logger.error(f"Sampling failed: {e}")

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

            if border_w == 0:
                parts.append("shadowcolor=black@0.35")
                parts.append("shadowx=2")
                parts.append("shadowy=2")
            
            vf = f"[0:v]drawtext={':'.join(parts)}[v]"
            return vf, txt_path

    def _run_ffmpeg_process(self, cmd: List[str], duration: Optional[float], out_path: str) -> Tuple[bool, str]:

        try:
            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                shell=True
            )
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
            except: pass

            full_error_log = "\n".join(err_lines)
            logger.error(f"FFmpeg failed with exit code {ret}.\nFile: {self.file_path}\nFull Stderr summary:\n{full_error_log}")

            important_msg = []
            for l in reversed(err_lines):
                l_s = l.strip()
                if not l_s: continue
                if any(x in l_s.lower() for x in ["error", "invalid", "failed", "could not", "no such"]):
                    important_msg.insert(0, l_s)
                if len(important_msg) >= 5: break
            
            if not important_msg:
                important_msg = [l.strip() for l in err_lines if l.strip()][-3:]
            
            error_summary = "\n".join(important_msg) if important_msg else f"FFmpeg 任务失败，退出码: {ret}"
            return False, error_summary

    def _get_duration(self, path: str) -> Optional[float]:
        try:
            cmd = [self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
            out = subprocess.check_output(cmd, text=True, errors='replace', shell=True).strip()
            return float(out)
        except: return None

    def _get_resolution(self, path: str) -> Tuple[Optional[int], Optional[int]]:
        try:
            cmd = [self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)]
            out = subprocess.check_output(cmd, text=True, errors='replace', shell=True).strip()
            if "x" in out:
                w, h = out.split("x", 1)
                return int(w), int(h)
        except: pass
        return None, None
