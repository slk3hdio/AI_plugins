from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

# import typer

BodyFormat = Literal["markdown", "text"]
SECTION_FILE_RE = re.compile(r"[^a-z0-9]+")
CAPTION_RE = re.compile(
    r"^(?P<kind>Figure|Fig\.?|Table)\s*(?P<number>[A-Za-z0-9.\-]+)\s*[:.\-]?\s*(?P<title>.*)$",
    re.IGNORECASE,
)


def _lazy_docling_import() -> tuple:
    try:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        return (
            PyPdfiumDocumentBackend,
            InputFormat,
            PdfPipelineOptions,
            DocumentConverter,
            PdfFormatOption,
        )
    except ImportError as exc:
        raise ImportError("docling is not installed. Install it first with `uv add docling` or `pip install docling`.") from exc


@dataclass
class ParseConfig:
    input_path: Path
    output_dir: Path
    artifacts_path: Path | None
    body_format: BodyFormat
    include_document_json: bool = False
    image_scale: float = 2.0
    timeout_seconds: float | None = 120.0


def _list_pdf_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file, got: {input_path}")
        return [input_path]

    if not input_path.exists():
        raise ValueError(f"Input path does not exist: {input_path}")

    pdf_files = sorted(p for p in input_path.rglob("*.pdf") if p.is_file())
    if not pdf_files:
        raise ValueError(f"No PDF files found under: {input_path}")

    return pdf_files


def _safe_name(value: str, fallback: str = "item", max_len: int = 80) -> str:
    cleaned = SECTION_FILE_RE.sub("_", value.lower()).strip("_")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len].strip("_") or fallback


def _safe_stem(path: Path) -> str:
    return _safe_name(path.stem, fallback="paper", max_len=120)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _join_nonempty(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line.strip()).strip()


def _build_text_index(doc_dict: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["self_ref"]: item
        for item in doc_dict.get("texts", [])
        if isinstance(item, dict) and "self_ref" in item
    }


def _ref_text(refs: list[dict[str, Any]], text_index: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    for ref in refs or []:
        target = text_index.get(ref.get("$ref", ""))
        if target:
            text = (target.get("text") or "").strip()
            if text:
                lines.append(text)
    return " ".join(lines).strip()


def _extract_title_from_doc(doc_dict: dict[str, Any], markdown_text: str, source: Path) -> str:
    for item in doc_dict.get("texts", []):
        if item.get("label") == "section_header":
            text = (item.get("text") or "").strip()
            if text and text.lower() != "abstract":
                return text
    for line in markdown_text.splitlines():
        if line.startswith("## "):
            return line[3:].strip()
    return source.stem


def _split_markdown_sections(markdown_text: str) -> tuple[str, list[dict[str, str]]]:
    lines = markdown_text.splitlines()
    preamble: list[str] = []
    sections: list[dict[str, str]] = []
    paper_title_seen = False
    current_title: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip()
            if not paper_title_seen:
                paper_title_seen = True
                continue
            if current_title is None:
                current_title = heading
                continue
            sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})
            current_title = heading
            current_lines = []
            continue

        if not paper_title_seen or current_title is None:
            preamble.append(line)
        else:
            current_lines.append(line)

    if current_title is not None:
        sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})

    return "\n".join(preamble).strip(), sections


def _extract_people_blocks(preamble_text: str) -> tuple[str, str]:
    author_lines: list[str] = []
    affiliation_lines: list[str] = []

    for raw_line in preamble_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if (
            "@" in line
            or re.match(r"^\d+\s", line)
            or any(
                token in lower
                for token in (
                    "university",
                    "institute",
                    "laboratory",
                    "department",
                    "school",
                    "college",
                    "corresponding author",
                    "state key",
                    "academy",
                )
            )
        ):
            affiliation_lines.append(line)
        else:
            author_lines.append(line)

    return _join_nonempty(author_lines), _join_nonempty(affiliation_lines)


def _convert_body_content(content: str, body_format: BodyFormat) -> str:
    if body_format == "markdown":
        return content.strip()

    converted_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "<!-- image -->":
            continue
        if stripped.startswith("- "):
            converted_lines.append(stripped)
        else:
            converted_lines.append(stripped)
    return "\n".join(converted_lines).strip()


def _section_extension(body_format: BodyFormat) -> str:
    return "md" if body_format == "markdown" else "txt"


def _normalize_section_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def _clean_caption_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" .:-")
    return cleaned or "untitled"


def _caption_metadata(caption_text: str, fallback_kind: str, fallback_index: int) -> dict[str, str]:
    match = CAPTION_RE.match(caption_text.strip())
    if match:
        kind = match.group("kind")
        raw_number = match.group("number")
        title = _clean_caption_title(match.group("title"))
        display_id = f"{'Figure' if kind.lower().startswith('fig') else 'Table'} {raw_number}"
    else:
        kind = fallback_kind
        raw_number = str(fallback_index)
        title = _clean_caption_title(caption_text)
        display_id = f"{fallback_kind} {fallback_index}"

    return {
        "kind": "figure" if kind.lower().startswith("fig") else "table",
        "display_id": display_id,
        "number": raw_number,
        "title": title,
    }


def _reference_patterns(display_id: str, kind: str) -> list[str]:
    number = display_id.split(" ", 1)[1] if " " in display_id else display_id
    if kind == "figure":
        return [rf"\bFigure\s+{re.escape(number)}\b", rf"\bFig\.?\s+{re.escape(number)}\b"]
    return [rf"\bTable\s+{re.escape(number)}\b"]


def _extract_reference_snippets(text: str, display_id: str, kind: str) -> list[str]:
    snippets: list[str] = []
    for pattern in _reference_patterns(display_id, kind):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 180)
            snippet = " ".join(text[start:end].split())
            if snippet and snippet not in snippets:
                snippets.append(snippet)
    return snippets[:8]


def _export_tables(
    doc,
    doc_dict: dict[str, Any],
    output_dir: Path,
    body_text: str,
) -> list[dict[str, Any]]:
    text_index = _build_text_index(doc_dict)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, Any]] = []

    for idx, table in enumerate(doc.tables, start=1):
        raw_table = (doc_dict.get("tables") or [])[idx - 1]
        caption_text = _ref_text(raw_table.get("captions", []), text_index)
        meta = _caption_metadata(caption_text, "Table", idx)
        slug = _safe_name(f"{meta['display_id']}_{meta['title']}", fallback=f"table_{idx:03d}")
        base_path = tables_dir / slug

        csv_path = base_path.with_suffix(".csv")

        try:
            dataframe = table.export_to_dataframe(doc)
            dataframe.to_csv(csv_path, index=False, encoding="utf-8")
        except Exception as exc:
            _write_text(csv_path.with_suffix(".error.txt"), f"CSV export failed: {exc}\n")
        exported.append(
            {
                "index": idx,
                "display_id": meta["display_id"],
                "title": meta["title"],
                "caption": caption_text,
                "page_no": ((raw_table.get("prov") or [{}])[0]).get("page_no"),
                "references_in_text": _extract_reference_snippets(body_text, meta["display_id"], "table"),
                "files": {
                    "csv": str(csv_path),
                },
            }
        )

    return exported


def _export_figures(
    doc,
    doc_dict: dict[str, Any],
    output_dir: Path,
    body_text: str,
) -> list[dict[str, Any]]:
    text_index = _build_text_index(doc_dict)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, Any]] = []

    for idx, picture in enumerate(doc.pictures, start=1):
        raw_picture = (doc_dict.get("pictures") or [])[idx - 1]
        caption_text = _ref_text(raw_picture.get("captions", []), text_index)
        meta = _caption_metadata(caption_text, "Figure", idx)
        slug = _safe_name(f"{meta['display_id']}_{meta['title']}", fallback=f"figure_{idx:03d}")
        image_path = figures_dir / f"{slug}.png"

        try:
            image = picture.get_image(doc)
            if image is not None:
                image.save(image_path)
        except Exception as exc:
            _write_text(image_path.with_suffix(".error.txt"), f"Image export failed: {exc}\n")
        exported.append(
            {
                "index": idx,
                "display_id": meta["display_id"],
                "title": meta["title"],
                "caption": caption_text,
                "page_no": ((raw_picture.get("prov") or [{}])[0]).get("page_no"),
                "references_in_text": _extract_reference_snippets(body_text, meta["display_id"], "figure"),
                "files": {
                    "image": str(image_path),
                },
            }
        )

    return exported


def _save_paper_sections(
    paper_dir: Path,
    paper_title: str,
    authors_text: str,
    affiliations_text: str,
    sections: list[dict[str, str]],
    body_format: BodyFormat,
) -> dict[str, Any]:
    section_dir = paper_dir / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)
    ext = _section_extension(body_format)

    files: dict[str, Any] = {"sections": []}
    files["paper_title"] = paper_title
    files["authors"] = authors_text
    files["affiliations"] = affiliations_text

    section_index = 1
    for section in sections:
        title = _normalize_section_title(section["title"])
        content = section["content"].strip()
        if not title:
            continue

        if title.lower() == "abstract":
            abstract_path = paper_dir / f"abstract.{ext}"
            _write_text(abstract_path, content)
            files["abstract"] = str(abstract_path)
            continue

        if title.lower() == "references":
            references_path = paper_dir / f"references.{ext}"
            _write_text(references_path, content)
            files["references"] = str(references_path)
            continue

        filename = f"{section_index:02d}_{_safe_name(title, fallback=f'section_{section_index:02d}')}.{ext}"
        section_path = section_dir / filename
        _write_text(section_path, content)
        files["sections"].append(
            {"index": section_index, "title": title, "path": str(section_path)}
        )
        section_index += 1

    return files


def _build_manifest(
    source_pdf: Path,
    paper_dir: Path,
    paper_title: str,
    authors_text: str,
    affiliations_text: str,
    body_format: BodyFormat,
    doc_dict: dict[str, Any],
    section_files: dict[str, Any],
    figures: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_pdf": str(source_pdf),
        "paper_dir": str(paper_dir),
        "title": paper_title,
        "authors": authors_text,
        "affiliations": affiliations_text,
        "body_format": body_format,
        "pages_count": len(doc_dict.get("pages") or {}),
        "sections_count": len(section_files.get("sections", [])),
        "figures_count": len(figures),
        "tables_count": len(tables),
        "files": section_files,
        "figures": figures,
        "tables": tables,
    }


def parse_pdf(config: ParseConfig) -> list[dict[str, Any]]:
    (
        PyPdfiumDocumentBackend,
        InputFormat,
        PdfPipelineOptions,
        DocumentConverter,
        PdfFormatOption,
    ) = _lazy_docling_import()

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.document_timeout = config.timeout_seconds
    pipeline_options.generate_page_images = True
    pipeline_options.generate_picture_images = True
    pipeline_options.images_scale = config.image_scale
    if config.artifacts_path is not None:
        config.artifacts_path.mkdir(parents=True, exist_ok=True)
        pipeline_options.artifacts_path = config.artifacts_path

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )
        }
    )

    reports: list[dict[str, Any]] = []

    file_list = _list_pdf_files(config.input_path)
    is_single_file = len(file_list) == 1
    for pdf_file in file_list:
        result = converter.convert(pdf_file)
        doc = result.document
        doc_dict = doc.export_to_dict()
        markdown_text = doc.export_to_markdown()
        plain_text = doc.export_to_text()

        paper_dir = config.output_dir if is_single_file else config.output_dir / _safe_stem(pdf_file)
        paper_dir.mkdir(parents=True, exist_ok=True)

        preamble_text, sections = _split_markdown_sections(markdown_text)
        paper_title = _extract_title_from_doc(doc_dict, markdown_text, pdf_file)
        authors_text, affiliations_text = _extract_people_blocks(preamble_text)

        body_text = markdown_text if config.body_format == "markdown" else plain_text
        body_ext = "md" if config.body_format == "markdown" else "txt"
        body_path = paper_dir / f"paper_body.{body_ext}"
        _write_text(body_path, body_text)

        section_payload = [
            {
                "title": _normalize_section_title(section["title"]),
                "content": _convert_body_content(section["content"], config.body_format),
            }
            for section in sections
        ]

        body_only_sections = [
            section
            for section in section_payload
            if section["title"].strip().lower() != "references"
        ]
        body_only_text = "\n\n".join(
            [f"## {section['title']}\n\n{section['content']}".rstrip() for section in body_only_sections]
        ).strip()

        section_files = _save_paper_sections(
            paper_dir=paper_dir,
            paper_title=paper_title,
            authors_text=authors_text,
            affiliations_text=affiliations_text,
            sections=section_payload,
            body_format=config.body_format,
        )
        section_files["paper_body"] = str(body_path)
        _write_text(body_path, body_only_text)

        if config.include_document_json:
            document_json_path = paper_dir / "document.json"
            _write_json(document_json_path, doc_dict)
            section_files["document_json"] = str(document_json_path)

        figures = _export_figures(doc, doc_dict, paper_dir, body_text)
        tables = _export_tables(doc, doc_dict, paper_dir, body_text)

        manifest = _build_manifest(
            source_pdf=pdf_file,
            paper_dir=paper_dir,
            paper_title=paper_title,
            authors_text=authors_text,
            affiliations_text=affiliations_text,
            body_format=config.body_format,
            doc_dict=doc_dict,
            section_files=section_files,
            figures=figures,
            tables=tables,
        )
        _write_json(paper_dir / "manifest.json", manifest)

        summary = {
            "source_pdf": str(pdf_file),
            "paper_dir": str(paper_dir),
            "title": paper_title,
            # "authors": authors_text,
            # "affiliations": affiliations_text,
            "pages_count": manifest["pages_count"],
            # "sections_count": manifest["sections_count"],
            # "figures_count": manifest["figures_count"],
            # "tables_count": manifest["tables_count"],
            # "abstract": str(paper_dir / "abstract.md"),
            # "paper_content": str(paper_dir / "paper_body.md"),
            # "manifest": str(paper_dir / "manifest.json"),
        }
        _write_json(paper_dir / "summary.json", summary)
        reports.append(summary)

    return reports

def run(
    input_path: Path,
    output_dir: Path,
    # body_format: BodyFormat
    # include_document_json: bool
    timeout_seconds: float = 500.0
) -> list[dict[str, Any]]:
    """Parse scientific paper PDFs into AI-friendly structured outputs.

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
    """
    file_dir = Path(__file__).parent
    artifacts_path = file_dir / "artifacts"
    body_format = "markdown"
    include_document_json = False

    config = ParseConfig(
        input_path=input_path,
        output_dir=output_dir,
        artifacts_path=artifacts_path,
        body_format=body_format,
        include_document_json=include_document_json,
        timeout_seconds=timeout_seconds,
    )

    return parse_pdf(config)

