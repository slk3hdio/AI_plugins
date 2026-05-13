from __future__ import annotations

import json
import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pdf_analysis.main import ParseConfig, parse_pdf
from pdf_analysis.mcp_server_cli import parse_args

BodyFormat = Literal["markdown", "text"]
HOST = os.environ.get("PDF_ANALYSIS_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("PDF_ANALYSIS_MCP_PORT", "8765"))
MCP_PATH = os.environ.get("PDF_ANALYSIS_MCP_PATH", "/mcp")
DEFAULT_ARTIFACTS_DIR = ROOT_DIR / "pdf_analysis" / "artifacts"

server = FastMCP(
    "paper-pdf-analysis",
    host=HOST,
    port=PORT,
    streamable_http_path=MCP_PATH,
)


def _resolve_user_path(path_str: str | None, fallback: Path | None = None) -> Path | None:
    if not path_str:
        return fallback
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()


@server.tool()
def parse_paper(
    pdf_path: str,
    output_dir: str,
    body_format: BodyFormat = "markdown",
    # document_json: bool = False,
    timeout_seconds: float = 500,
) -> dict:
    """Parse scientific paper PDFs into AI-friendly structured outputs.

    The parameter `pdf_path` is the path to a PDF file or a directory containing PDF files.

    For each paper, the tool writes:
    - `summary.json`: compact entry point with title, page count, and manifest path
    - `manifest.json`: detailed file map and extracted figure/table metadata
    - `paper_body.md` or `paper_body.txt`: main paper body without references
    - `abstract.*`: abstract only
    - `references.*`: references only
    - `sections/`: one file per detected section
    - `figures/`: extracted figure PNG files only
    - `tables/`: extracted table CSV files only

    Figure and table titles, captions, page numbers, and body-text reference
    snippets are stored in `manifest.json`. The file can be large, so don't read the full content directly.

    Returns:
    - `count`: number of processed PDFs
    - `papers`: a list of per-paper summaries
    """
    document_json = False
    config = ParseConfig(
        input_path=_resolve_user_path(pdf_path),
        output_dir=_resolve_user_path(output_dir),
        artifacts_path=DEFAULT_ARTIFACTS_DIR,
        body_format=body_format,
        include_document_json=document_json,
        timeout_seconds=timeout_seconds,
    )

    # StdIO MCP requires stdout to remain protocol-only. Suppress noisy
    # third-party progress bars and model-loading logs during parsing.
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        reports = parse_pdf(config)

    return {"count": len(reports), "papers": reports}


def main() -> None:
    args = parse_args()

    if args.command in (None, "serve"):
        transport = getattr(args, "transport", "streamable-http")
        server.run(transport=transport)
        return

    if args.command == "parse":
        result = parse_paper(
            pdf_path=args.pdf_path,
            output_dir=args.output_dir,
            body_format=args.body_format,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
