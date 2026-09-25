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
    def clean_text(text: str) -> str:
        """Sanitize extracted text to remove CID codes, non-printable characters, and excess whitespace."""
        if not text:
            return ""
        # 1. Remove non-printable / control chars except \n, \t, \r
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        # 2. Remove CID font artifacts: (cid:123)
        text = re.sub(r"\(cid:\d+\)", " ", text)
        # 3. Fix broken hyphenation at line breaks: "arbitra-\ntion" -> "arbitration"
        text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
        # 4. Collapse multiple spaces / horizontal tabs
        text = re.sub(r"[ \t]+", " ", text)
        # 5. Normalize excess newlines (maximum two consecutive)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def parse_pdf_bytes(file_bytes: bytes, filename: str) -> Dict:
        """Extract text from PDF byte stream prioritizing PyMuPDF (fitz) for high fidelity."""
        text_pages = []
        page_count = 0

        # Attempt PyMuPDF (fitz) first for accurate font mapping and clean extraction
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page_count = len(doc)
            for page_idx, page in enumerate(doc, 1):
                page_text = page.get_text("text") or ""
                cleaned = DocumentParser.clean_text(page_text)
                if cleaned:
                    text_pages.append(f"[Page {page_idx}]\n{cleaned}")
        except Exception as e_fitz:
            logger.warning(f"PyMuPDF extraction issue on {filename}: {e_fitz}. Falling back to pypdf...")
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_bytes))
                page_count = len(reader.pages)
                for page_idx, page in enumerate(reader.pages, 1):
                    page_text = page.extract_text() or ""
                    cleaned = DocumentParser.clean_text(page_text)
                    if cleaned:
                        text_pages.append(f"[Page {page_idx}]\n{cleaned}")
            except Exception as e_pdf:
                logger.error(f"Both PyMuPDF and pypdf failed to parse {filename}: {e_pdf}")
                raise ValueError(f"Could not extract text from PDF '{filename}': {str(e_pdf)}")

        full_text = "\n\n".join(text_pages)
        if not full_text.strip():
            raise ValueError(f"The PDF '{filename}' contains no readable text. Ensure it is not an image-only scan.")

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

        cleaned_text = DocumentParser.clean_text(decoded_text)
        if not cleaned_text:
            raise ValueError(f"The text file '{filename}' contains no readable content.")

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
