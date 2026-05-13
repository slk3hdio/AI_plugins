from __future__ import annotations

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    file_name = os.path.basename(sys.argv[0]) if sys.argv else os.path.basename(__file__)
    script_name = os.environ.get("PARSE_PAPER_FILENAME", file_name)

    parser = argparse.ArgumentParser(
        description="Run the paper PDF MCP server or parse papers from the CLI.",
        prog=script_name,
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the MCP server.")
    serve_parser.add_argument(
        "--transport",
        choices=("streamable-http", "stdio"),
        default="streamable-http",
        help="MCP transport to use.",
    )

    parse_parser = subparsers.add_parser(
        "parse",
        help="Parse paper PDFs directly from the CLI.",
    )
    parse_parser.add_argument("pdf_path", help="Path to a PDF file or a directory of PDFs.")
    parse_parser.add_argument("output_dir", help="Directory where parsed outputs will be written.")
    parse_parser.add_argument(
        "--body-format",
        choices=("markdown", "text"),
        default="markdown",
        help="Main body export format.",
    )
    parse_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=500,
        help="Per-document parsing timeout in seconds.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
