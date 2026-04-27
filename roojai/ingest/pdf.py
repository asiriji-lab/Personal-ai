from __future__ import annotations

from pathlib import Path


def extract_pdf_text(file_path: Path) -> str:
    try:
        import fitz  # type: ignore
    except ImportError:
        try:
            import pdfplumber  # type: ignore
        except ImportError as exc:
            raise ValueError("PDF ingest requires PyMuPDF or pdfplumber.") from exc

        with pdfplumber.open(file_path) as pdf:
            return "\n\n".join((page.extract_text() or "").strip() for page in pdf.pages).strip()

    with fitz.open(file_path) as document:
        return "\n\n".join(page.get_text().strip() for page in document).strip()
