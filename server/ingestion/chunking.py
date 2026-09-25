"""Context-Enriched Recursive Chunking Strategy for Legal Texts."""
from typing import List, Dict, Optional
import os
import re
import logging

logger = logging.getLogger(__name__)

class ContextEnrichedRecursiveChunker:
    """Recursively splits legal texts while enriching each chunk with statutory metadata headers."""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        separators: Optional[List[str]] = None,
    ):
        self.chunk_size = chunk_size or int(os.getenv("CHUNK_SIZE", "500"))
        self.chunk_overlap = chunk_overlap or int(os.getenv("CHUNK_OVERLAP", "75"))
        self.separators = separators or ["\n\n", "\n", ". ", "; ", " ", ""]

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """Recursive character splitting algorithm."""
        final_chunks: List[str] = []
        separator = separators[-1]
        new_separators = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1 :]
                break

        splits = text.split(separator) if separator else list(text)

        good_splits: List[str] = []
        for s in splits:
            if separator and good_splits:
                # Merge with previous if small enough
                if len(good_splits[-1]) + len(s) + len(separator) <= self.chunk_size:
                    good_splits[-1] = f"{good_splits[-1]}{separator}{s}"
                    continue

            if len(s) <= self.chunk_size:
                good_splits.append(s)
            else:
                if new_separators:
                    sub_splits = self._split_text(s, new_separators)
                    good_splits.extend(sub_splits)
                else:
                    # Hard slice fallback
                    for j in range(0, len(s), self.chunk_size - self.chunk_overlap):
                        good_splits.append(s[j : j + self.chunk_size])

        # Apply overlap consolidation
        current_chunk = ""
        for s in good_splits:
            s_clean = s.strip()
            if not s_clean:
                continue

            if not current_chunk:
                current_chunk = s_clean
            elif len(current_chunk) + len(s_clean) + 1 <= self.chunk_size:
                current_chunk = f"{current_chunk} {s_clean}"
            else:
                final_chunks.append(current_chunk)
                # Overlap tail
                overlap_text = current_chunk[-self.chunk_overlap :] if len(current_chunk) > self.chunk_overlap else ""
                current_chunk = f"{overlap_text} {s_clean}".strip()

        if current_chunk and current_chunk not in final_chunks:
            final_chunks.append(current_chunk)

        return final_chunks

    def chunk_document(self, qa_record: Dict) -> List[Dict]:
        """Split a legal Q&A record and enrich each chunk with contextual headers.

        Args:
            qa_record: Dict containing 'id', 'Instruction', 'Response', optional 'category'.

        Returns:
            List of chunk dicts ready for embedding and indexing.
        """
        doc_id = qa_record["id"]
        instruction = str(qa_record.get("Instruction", "")).strip()
        response = str(qa_record.get("Response", "")).strip()
        category = qa_record.get("category", "Constitution & Precedents")
        
        title = instruction[:70] + "..." if len(instruction) > 70 else instruction
        full_text = f"Question: {instruction}\n\nAnswer: {response}"

        if len(full_text) <= self.chunk_size:
            raw_chunks = [full_text]
        else:
            raw_chunks = self._split_text(full_text, self.separators)

        enriched_chunks = []
        total_chunks = len(raw_chunks)

        for idx, chunk_text in enumerate(raw_chunks):
            chunk_id = f"qa_{doc_id}_c{idx}" if total_chunks > 1 else f"qa_{doc_id}"
            
            # Context enrichment prefix
            context_header = (
                f"[Context: Indian Legal Q&A | Precedent ID: {doc_id} | "
                f"Part: {idx + 1}/{total_chunks} | Category: {category} | Topic: {title}]\n"
            )
            enriched_content = f"{context_header}{chunk_text}"

            enriched_chunks.append({
                "chunk_id": chunk_id,
                "parent_id": str(doc_id),
                "chunk_index": idx,
                "total_chunks": total_chunks,
                "content": enriched_content,
                "raw_text": chunk_text,
                "title": title,
                "instruction": instruction[:500],
                "response": response[:500],
                "category": category,
                "source": "Indian Law Dataset",
            })

        return enriched_chunks

    def chunk_raw_document(
        self,
        doc_id: str,
        title: str,
        text: str,
        doc_type: str = "Uploaded Document",
        category: str = "User Upload",
    ) -> List[Dict]:
        """Split a raw text document (PDF/text) and enrich each chunk with contextual headers.

        Args:
            doc_id: Unique document identifier.
            title: Document title or filename.
            text: Extracted text content.
            doc_type: PDF, Text, Contract, FIR, etc.
            category: Domain category.

        Returns:
            List of chunk dictionaries formatted for vector store and BM25 index.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

        if len(clean_text) <= self.chunk_size:
            raw_chunks = [clean_text]
        else:
            raw_chunks = self._split_text(clean_text, self.separators)

        enriched_chunks = []
        total_chunks = len(raw_chunks)

        for idx, chunk_text in enumerate(raw_chunks):
            chunk_id = f"{doc_id}_c{idx}" if total_chunks > 1 else str(doc_id)

            context_header = (
                f"[Uploaded Document: {title} | ID: {doc_id} | Type: {doc_type} | "
                f"Part: {idx + 1}/{total_chunks} | Category: {category}]\n"
            )
            enriched_content = f"{context_header}{chunk_text}"

            enriched_chunks.append({
                "chunk_id": chunk_id,
                "parent_id": str(doc_id),
                "chunk_index": idx,
                "total_chunks": total_chunks,
                "content": enriched_content,
                "raw_text": chunk_text,
                "title": title,
                "instruction": f"Document: {title} (Part {idx + 1}/{total_chunks})",
                "response": chunk_text[:500],
                "category": category,
                "source": f"Upload: {title}",
                "doc_type": doc_type,
            })

        return enriched_chunks

