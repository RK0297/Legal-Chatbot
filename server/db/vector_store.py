import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
import json
from pathlib import Path
from typing import List, Dict, Optional
import logging
from tqdm import tqdm

import os

SERVER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = SERVER_DIR / "data"
DEFAULT_VECTOR_DB_DIR = Path(os.getenv("VECTOR_DB_PATH", str(DEFAULT_DATA_DIR / "vectordb")))
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw"

logger = logging.getLogger(__name__)

class VectorStore:
    """Manages ChromaDB vector persistence, embeddings, and similarity queries."""

    def __init__(
        self,
        persist_directory: Optional[Path] = None,
        embedding_model_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        self.persist_directory = Path(persist_directory or DEFAULT_VECTOR_DB_DIR)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.model_name = embedding_model_name or os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.collection_name = collection_name or os.getenv("VECTOR_DB_COLLECTION", "legal_qa")

        logger.info(f"Loading SentenceTransformer embedding model: {self.model_name}")
        self.embedding_model = SentenceTransformer(self.model_name)

        logger.info(f"Connecting to ChromaDB PersistentClient at {self.persist_directory}")
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """Retrieve existing ChromaDB collection or register a new one."""
        try:
            collection = self.client.get_collection(name=self.collection_name)
            count = collection.count()
            logger.info(f"Connected to collection '{self.collection_name}' ({count} records).")
            return collection
        except Exception:
            logger.info(f"Creating collection '{self.collection_name}'.")
            return self.client.create_collection(
                name=self.collection_name,
                metadata={"description": "Indian Law Q&A Dataset - Instruction-Response pairs"},
            )

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Encode textual inputs into 384-dimensional dense vectors."""
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def add_documents(self, qa_pairs: List[Dict], batch_size: int = 100):
        """Batch-embed and insert legal Q&A pairs into ChromaDB.

        Args:
            qa_pairs: List of dicts containing 'id', 'Instruction', and 'Response'.
            batch_size: Number of records processed per batch.
        """
        logger.info(f"Indexing {len(qa_pairs)} Q&A pairs into collection '{self.collection_name}'...")

        ids = []
        documents = []
        metadatas = []

        for qa in qa_pairs:
            doc_id = f"qa_{qa['id']}"
            ids.append(doc_id)

            combined_text = f"Question: {qa['Instruction']}\n\nAnswer: {qa['Response']}"
            documents.append(combined_text)

            instruction_str = str(qa['Instruction'])
            response_str = str(qa['Response'])
            
            # Generate clean title and metadata for citation transparency
            title_preview = instruction_str[:70] + "..." if len(instruction_str) > 70 else instruction_str
            metadata = {
                'id': str(qa['id']),
                'title': title_preview,
                'source': 'Indian Law Q&A Corpus',
                'category': 'Constitution & Precedents',
                'url': '',
                'instruction': instruction_str[:500],
                'response': response_str[:500],
                'instruction_length': str(len(instruction_str)),
                'response_length': str(len(response_str)),
            }
            metadatas.append(metadata)

        for i in tqdm(range(0, len(documents), batch_size), desc="Indexing batches"):
            batch_ids = ids[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]
            batch_meta = metadatas[i : i + batch_size]

            batch_embeds = self.generate_embeddings(batch_docs)
            self.collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta,
                embeddings=batch_embeds,
            )

        logger.info(f"Indexing complete. Total documents in collection: {self.collection.count()}")

    def add_chunks(self, chunks: List[Dict], batch_size: int = 100):
        """Batch-embed and insert pre-chunked records into ChromaDB.

        Args:
            chunks: List of chunk dictionaries containing 'chunk_id', 'content', 'title', etc.
            batch_size: Number of records per insertion batch.
        """
        if not chunks:
            return

        ids = [str(c["chunk_id"]) for c in chunks]
        documents = [str(c["content"]) for c in chunks]
        metadatas = []

        for c in chunks:
            metas = {
                "id": str(c.get("parent_id", c["chunk_id"])),
                "title": str(c.get("title", ""))[:100],
                "source": str(c.get("source", "Uploaded Document")),
                "category": str(c.get("category", "User Upload")),
                "url": "",
                "instruction": str(c.get("instruction", ""))[:500],
                "response": str(c.get("response", ""))[:500],
                "chunk_index": str(c.get("chunk_index", 0)),
                "total_chunks": str(c.get("total_chunks", 1)),
                "doc_type": str(c.get("doc_type", "user_upload")),
            }
            metadatas.append(metas)

        for i in range(0, len(documents), batch_size):
            b_ids = ids[i : i + batch_size]
            b_docs = documents[i : i + batch_size]
            b_metas = metadatas[i : i + batch_size]
            b_embeds = self.generate_embeddings(b_docs)
            self.collection.add(
                ids=b_ids,
                documents=b_docs,
                metadatas=b_metas,
                embeddings=b_embeds,
            )
        logger.info(f"Successfully added {len(chunks)} chunks to vector store. Total: {self.collection.count()}")

    def search(self, query: str, n_results: int = 5, filter_dict: Optional[Dict] = None) -> Dict:
        """Execute cosine similarity query against collection."""
        query_embedding = self.embedding_model.encode([query])[0].tolist()

        search_params = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
        }
        if filter_dict:
            search_params["where"] = filter_dict

        return self.collection.query(**search_params)

    def get_stats(self) -> Dict:
        """Fetch statistics and sample text metrics."""
        count = self.collection.count()
        sample_size = min(100, count)
        sample = self.collection.get(limit=sample_size) if count > 0 else {"metadatas": []}

        stats = {
            "total_qa_pairs": count,
            "total_documents": count,
            "collection_name": self.collection_name,
            "embedding_model": self.model_name,
            "categories": ["Constitution", "Civil Law", "Criminal Law", "Procedural Codes"],
            "document_types": ["Q&A Precedents", "Statutory Provisions"],
            "avg_instruction_length": 0,
            "avg_response_length": 0,
        }

        if sample and sample.get("metadatas"):
            inst_lens = [int(m["instruction_length"]) for m in sample["metadatas"] if "instruction_length" in m]
            resp_lens = [int(m["response_length"]) for m in sample["metadatas"] if "response_length" in m]
            if inst_lens:
                stats["avg_instruction_length"] = sum(inst_lens) // len(inst_lens)
            if resp_lens:
                stats["avg_response_length"] = sum(resp_lens) // len(resp_lens)

        return stats

    def reset_database(self):
        """Purge and recreate the vector collection."""
        logger.warning(f"Resetting collection '{self.collection_name}'...")
        self.client.delete_collection(name=self.collection_name)
        self.collection = self._get_or_create_collection()
        logger.info("Database reset complete.")

def load_qa_data(filename: str = "legal_data_all.json", data_dir: Optional[Path] = None) -> List[Dict]:
    """Safely load raw Q&A dataset from filesystem."""
    directory = Path(data_dir) if data_dir else DEFAULT_RAW_DIR
    filepath = directory / filename

    logger.info(f"Loading Q&A dataset from: {filepath}")
    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Successfully loaded {len(data)} items from {filename}")
        return data
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return []
