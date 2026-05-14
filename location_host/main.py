import uvicorn
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

from web_server import DATA_DIR

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)

    log_file = os.path.join(LOG_DIR, "server.log")

    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


if __name__ == "__main__":
    setup_logging()

    logger = logging.getLogger("location_host")
    logger.info("=" * 50)
    logger.info("位置接收服务器启动")
    logger.info(f"数据目录: {os.path.abspath(DATA_DIR)}")
    logger.info(f"日志目录: {os.path.abspath(LOG_DIR)}")
    logger.info("API 地址: http://0.0.0.0:5000/api/location")
    logger.info("=" * 50)

    uvicorn.run("web_server:app", host="0.0.0.0", port=5000, reload=True, log_config=None)
