from __future__ import annotations

import argparse
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import uvicorn

from job_manager import JobManager
from mcp_server import create_http_app, create_stdio_server


LOG_DIR = Path(__file__).parent / "logs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the PDF analysis MCP server.")
    subparsers = parser.add_subparsers(dest="transport", required=True)

    http_parser = subparsers.add_parser("http", help="Run the server over HTTP")
    http_parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    http_parser.add_argument("--port", type=int, default=8001, help="HTTP bind port")
    http_parser.add_argument("--queue-max-size", type=int, default=16, help="Maximum queued jobs")

    stdio_parser = subparsers.add_parser("stdio", help="Run the server over stdio")
    stdio_parser.add_argument("--queue-max-size", type=int, default=16, help="Maximum queued jobs")
    return parser


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = TimedRotatingFileHandler(
        LOG_DIR / "server.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def main() -> None:
    args = build_parser().parse_args()
    configure_logging()

    job_manager = JobManager(queue_max_size=args.queue_max_size)
    if args.transport == "http":
        app = create_http_app(job_manager)
        uvicorn.run(app, host=args.host, port=args.port, log_config=None)
        return

    server = create_stdio_server(job_manager)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
