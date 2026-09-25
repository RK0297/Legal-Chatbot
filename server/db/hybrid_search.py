"""Hybrid Search Engine combining Dense Vector Retrieval, Sparse BM25, and Cross-Encoder Re-ranking."""
from typing import List, Dict, Optional, Tuple
import re
import pickle
import logging
from pathlib import Path
from rank_bm25 import BM25Okapi

import os
from server.db.vector_store import VectorStore

SERVER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BM25_DIR = SERVER_DIR / "data" / "bm25"

logger = logging.getLogger(__name__)

def tokenize_legal_text(text: str) -> List[str]:
    """Tokenize legal text for BM25 search (alphanumeric tokens + statutory identifiers)."""
    clean_text = text.lower()
    # Retain section numbers, article numbers, and words
    tokens = re.findall(r"\b[a-z0-9]+(?:[-_][a-z0-9]+)*\b", clean_text)
    return tokens

class BM25Index:
    """In-memory and file-backed BM25 sparse index."""

    def __init__(self, persist_path: Optional[Path] = None):
        self.persist_path = persist_path or (DEFAULT_BM25_DIR / "bm25_store.pkl")
        self.bm25: Optional[BM25Okapi] = None
        self.corpus_ids: List[str] = []
        self.corpus_docs: List[str] = []
        self.corpus_metas: List[Dict] = []
        self.load_if_exists()

    def build_index(self, records: List[Dict]):
        """Index a list of document dicts with 'id', 'content', and 'metadata'."""
        logger.info(f"Building BM25 sparse index for {len(records)} records...")
        tokenized_corpus = []
        self.corpus_ids = []
        self.corpus_docs = []
        self.corpus_metas = []

        for item in records:
            doc_id = str(item.get("id") or item.get("chunk_id"))
            content = str(item.get("content") or item.get("document") or "")
            meta = item.get("metadata") or {}

            tokens = tokenize_legal_text(content)
            if not tokens:
                tokens = ["empty"]

            tokenized_corpus.append(tokens)
            self.corpus_ids.append(doc_id)
            self.corpus_docs.append(content)
            self.corpus_metas.append(meta)

        self.bm25 = BM25Okapi(tokenized_corpus)
        self.save()
        logger.info(f"BM25 index successfully built with {len(self.corpus_ids)} entries.")

    def add_records(self, records: List[Dict]):
        """Incrementally append records to BM25 index and refresh ranking model."""
        if not records:
            return

        logger.info(f"Incrementally adding {len(records)} records to BM25 index...")
        for item in records:
            doc_id = str(item.get("id") or item.get("chunk_id"))
            content = str(item.get("content") or item.get("document") or "")
            meta = item.get("metadata") or {}

            self.corpus_ids.append(doc_id)
            self.corpus_docs.append(content)
            self.corpus_metas.append(meta)

        tokenized_corpus = []
        for doc in self.corpus_docs:
            tokens = tokenize_legal_text(doc)
            tokenized_corpus.append(tokens if tokens else ["empty"])

        self.bm25 = BM25Okapi(tokenized_corpus)
        self.save()
        logger.info(f"BM25 index successfully updated. Total records: {len(self.corpus_ids)}")

    def search(self, query: str, top_k: int = 25) -> List[Dict]:
        """Search BM25 index and return ranked results."""
        if not self.bm25 or not self.corpus_ids:
            return []

        tokens = tokenize_legal_text(query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            results.append({
                "id": self.corpus_ids[idx],
                "score": float(scores[idx]),
                "content": self.corpus_docs[idx],
                "metadata": self.corpus_metas[idx],
                "retriever": "bm25",
            })
        return results

    def save(self):
        """Persist BM25 index to disk."""
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persist_path, "wb") as f:
                pickle.dump({
                    "bm25": self.bm25,
                    "ids": self.corpus_ids,
                    "docs": self.corpus_docs,
                    "metas": self.corpus_metas,
                }, f)
            logger.info(f"BM25 index saved to {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to persist BM25 index: {e}")

    def load_if_exists(self) -> bool:
        """Load persisted BM25 index from disk if present."""
        if self.persist_path.exists():
            try:
                with open(self.persist_path, "rb") as f:
                    data = pickle.load(f)
                    self.bm25 = data["bm25"]
                    self.corpus_ids = data["ids"]
                    self.corpus_docs = data["docs"]
                    self.corpus_metas = data["metas"]
                logger.info(f"Loaded existing BM25 index ({len(self.corpus_ids)} records) from {self.persist_path}")
                return True
            except Exception as e:
                logger.warning(f"Could not load BM25 index from {self.persist_path}: {e}")
        return False


class CrossEncoderReranker:
    """Re-ranks candidate documents using cross-attention joint scoring."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading Cross-Encoder re-ranker: {self.model_name}")
            self._model = CrossEncoder(self.model_name)

    def rerank(self, query: str, candidates: List[Dict], top_k: int = 5) -> List[Dict]:
        """Jointly score (query, document) pairs and return top_k candidates."""
        if not candidates:
            return []

        try:
            self._load_model()
            pairs = [[query, c["content"]] for c in candidates]
            scores = self._model.predict(pairs)

            scored_candidates = []
            for candidate, score in zip(candidates, scores):
                c = dict(candidate)
                c["rerank_score"] = float(score)
                scored_candidates.append(c)

            scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
            return scored_candidates[:top_k]
        except Exception as e:
            logger.error(f"Cross-encoder reranking error: {e}. Falling back to pre-rerank order.")
            return candidates[:top_k]


class HybridSearchEngine:
    """Orchestrates Dense Vector Search, Sparse BM25 Search, RRF, and Cross-Encoder Re-ranking."""

    def __init__(
        self,
        vector_store: VectorStore,
        bm25_index: Optional[BM25Index] = None,
        reranker: Optional[CrossEncoderReranker] = None,
        rrf_k: Optional[int] = None,
    ):
        self.vector_store = vector_store
        self.bm25_index = bm25_index or BM25Index()
        self.reranker = reranker or CrossEncoderReranker()
        self.rrf_k = rrf_k or int(os.getenv("RRF_K", "60"))

    def reciprocal_rank_fusion(
        self,
        dense_results: List[Dict],
        sparse_results: List[Dict],
        limit: int = 15,
    ) -> List[Dict]:
        """Combine candidate rankings using Reciprocal Rank Fusion (RRF)."""
        rrf_scores: Dict[str, float] = {}
        doc_store: Dict[str, Dict] = {}

        # Process dense rankings
        for rank, item in enumerate(dense_results):
            doc_id = item["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (self.rrf_k + (rank + 1)))
            if doc_id not in doc_store:
                doc_store[doc_id] = item

        # Process sparse rankings
        for rank, item in enumerate(sparse_results):
            doc_id = item["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (self.rrf_k + (rank + 1)))
            if doc_id not in doc_store:
                doc_store[doc_id] = item

        # Sort by merged RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)

        merged: List[Dict] = []
        for doc_id in sorted_ids[:limit]:
            candidate = dict(doc_store[doc_id])
            candidate["rrf_score"] = rrf_scores[doc_id]
            merged.append(candidate)

        return merged

    def search(
        self,
        query: str,
        top_k: int = 5,
        dense_limit: int = 25,
        sparse_limit: int = 25,
        enable_rerank: bool = True,
        filter_dict: Optional[Dict] = None,
    ) -> List[Dict]:
        """Execute complete Multi-Stage Hybrid Search."""
        dense_candidates: List[Dict] = []
        sparse_candidates: List[Dict] = []

        # 1. Dense Vector Retrieval
        try:
            dense_res = self.vector_store.search(query, n_results=dense_limit, filter_dict=filter_dict)
            docs = dense_res.get("documents", [[]])[0]
            metas = dense_res.get("metadatas", [[]])[0]
            dists = dense_res.get("distances", [[]])[0] if "distances" in dense_res else [1.0] * len(docs)
            ids = dense_res.get("ids", [[]])[0] if "ids" in dense_res else [f"doc_{i}" for i in range(len(docs))]

            for doc_id, doc, meta, dist in zip(ids, docs, metas, dists):
                dense_candidates.append({
                    "id": doc_id,
                    "content": doc,
                    "metadata": meta,
                    "dense_distance": float(dist),
                    "similarity": max(0.0, 1.0 - float(dist)),
                    "retriever": "dense",
                })
        except Exception as e:
            logger.error(f"Dense search failed: {e}")

        # 2. Sparse BM25 Retrieval
        if os.getenv("ENABLE_BM25", "true").lower() == "true":
            try:
                sparse_candidates = self.bm25_index.search(query, top_k=sparse_limit)
            except Exception as e:
                logger.error(f"BM25 search failed: {e}")

        # 3. Reciprocal Rank Fusion
        if sparse_candidates and dense_candidates:
            merged_candidates = self.reciprocal_rank_fusion(
                dense_candidates, sparse_candidates, limit=max(top_k * 3, 15)
            )
        else:
            merged_candidates = dense_candidates or sparse_candidates

        # 4. Cross-Encoder Re-ranking
        if enable_rerank and os.getenv("ENABLE_RERANKER", "true").lower() == "true" and merged_candidates:
            final_results = self.reranker.rerank(query, merged_candidates, top_k=top_k)
        else:
            final_results = merged_candidates[:top_k]

        return final_results
