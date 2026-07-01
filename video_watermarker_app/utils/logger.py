#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from GLOBAL import LOG_FOLDER, LOG_FILE


def setup_logger():
    """配置全局日志"""

    log_dir = Path(LOG_FOLDER)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = Path(LOG_FILE)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

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

# 供外部直接调用
setup_logger()
logger = logging.getLogger()
