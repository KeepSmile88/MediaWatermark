import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from video_watermarker_app.GLOBAL import APP_EN_NAME

LOG_DIR_NAME = "logs"

def setup_logger():
    """配置全局日志"""
    # 获取 %APPDATA%/VideoWatermarker/logs
    app_data = os.getenv('APPDATA')
    if not app_data:
        app_data = os.path.expanduser("~") # Fallback to user home if APPDATA is missing

    log_dir = Path(app_data) / APP_EN_NAME / LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / "app.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler
    if logger.handlers:
        return

    # 格式
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=5*1024*1024, 
        backupCount=5, 
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    logger.info(f"Logger initialized. Log file: {log_file}")

setup_logger()
logger = logging.getLogger()
