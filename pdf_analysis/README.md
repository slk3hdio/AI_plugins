# PDF Analysis Tool

This folder contains a Docling-based parser tailored for scientific papers.

## Features

- Extract paper structure into separate files
- Save title, authors, affiliations, abstract, references, and section files
- Extract figures and tables with caption-based names
- Capture figure/table references from the body text
- Export a single AI-friendly `manifest.json` per paper
- Provide an MCP server over standard input/output

## Install

```bash
uv add docling
```

## Usage

```bash
python pdf_analysis/main.py path/to/paper.pdf
python pdf_analysis/main.py path/to/pdf_dir --output-dir pdf_analysis/outputs
python pdf_analysis/main.py path/to/paper.pdf --body-format text
pdf_analysis\parse_paper.bat test\paper.pdf pdf_analysis\outputs
```

Default behavior:

- exports only one body file: `paper_body.md` or `paper_body.txt`
- does not export `document.json`
- always exports `manifest.json`, `summary.json`, sections, figures, and tables

## MCP

Run the MCP server over HTTP:

```bash
python pdf_analysis/mcp_server.py serve
```

Run the MCP server over stdio:

```bash
python pdf_analysis/mcp_server.py serve --transport stdio
```

Parse papers directly from the CLI through the same entrypoint:

```bash
python pdf_analysis/mcp_server.py parse test/paper.pdf pdf_analysis/outputs
python pdf_analysis/mcp_server.py parse test/paper.pdf pdf_analysis/outputs --body-format text --timeout-seconds 300
```

Windows batch wrapper for CLI parsing only:

```bat
pdf_analysis\parse_paper.bat test\paper.pdf pdf_analysis\outputs
pdf_analysis\parse_paper.bat test\paper.pdf pdf_analysis\outputs --body-format text --timeout-seconds 300
```

Main tool:

- `parse_paper(pdf_path, output_dir, body_format="markdown", timeout_seconds=500)`
