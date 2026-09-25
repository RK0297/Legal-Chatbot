"""Document Parser for Legal Briefs, Petitions, FIRs, and Contracts (PDF / TXT / MD)."""
import io
import re
import logging
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class DocumentParser:
    """Parses legal documents (PDF, TXT, MD) and extracts clean normalized text."""

    @staticmethod
    def parse_pdf_bytes(file_bytes: bytes, filename: str) -> Dict:
        """Extract text from PDF byte stream."""
        text_pages = []
        page_count = 0

        # Attempt PyPDF first
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            page_count = len(reader.pages)
            for page_idx, page in enumerate(reader.pages, 1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_pages.append(f"[Page {page_idx}]\n{page_text.strip()}")
        except Exception as e:
            logger.warning(f"pypdf extraction error on {filename}: {e}. Trying fitz/PyMuPDF...")
            try:
                import fitz
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                page_count = len(doc)
                for page_idx, page in enumerate(doc, 1):
                    page_text = page.get_text() or ""
                    if page_text.strip():
                        text_pages.append(f"[Page {page_idx}]\n{page_text.strip()}")
            except Exception as e2:
                logger.error(f"Both pypdf and fitz failed to parse {filename}: {e2}")
                raise ValueError(f"Could not extract text from PDF '{filename}': {str(e2)}")

        full_text = "\n\n".join(text_pages)
        title = Path(filename).stem.replace("_", " ").replace("-", " ").title()

        return {
            "filename": filename,
            "title": title,
            "page_count": page_count,
            "text": full_text,
            "char_count": len(full_text),
            "doc_type": "PDF",
        }

    @staticmethod
    def parse_text_bytes(file_bytes: bytes, filename: str) -> Dict:
        """Decode and normalize plain text or markdown byte stream."""
        encodings = ["utf-8", "latin-1", "cp1252"]
        decoded_text = ""
        for enc in encodings:
            try:
                decoded_text = file_bytes.decode(enc)
                break
            except (UnicodeDecodeError, AttributeError):
                continue

        if not decoded_text:
            raise ValueError(f"Failed to decode text file '{filename}' with standard encodings.")

        # Clean multiple trailing linebreaks
        cleaned_text = re.sub(r"\n{3,}", "\n\n", decoded_text.strip())
        title = Path(filename).stem.replace("_", " ").replace("-", " ").title()

        return {
            "filename": filename,
            "title": title,
            "page_count": 1,
            "text": cleaned_text,
            "char_count": len(cleaned_text),
            "doc_type": "Text/Markdown",
        }

    @classmethod
    def parse_file(cls, file_bytes: bytes, filename: str) -> Dict:
        """Route to appropriate parser based on file extension."""
        lower_name = filename.lower()
        if lower_name.endswith(".pdf"):
            return cls.parse_pdf_bytes(file_bytes, filename)
        elif lower_name.endswith((".txt", ".md", ".text")):
            return cls.parse_text_bytes(file_bytes, filename)
        else:
            raise ValueError(f"Unsupported file format '{filename}'. Supported: .pdf, .txt, .md")
