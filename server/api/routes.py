from fastapi import APIRouter, HTTPException, Query, Depends, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from datetime import datetime
import json
import uuid
import os
import logging
from typing import Optional
from server.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    StatsResponse,
    BuildRequest,
    SearchResponse,
    DocumentResponse,
    EvaluateRequest,
    EvaluateResponse,
    DocumentUploadResponse,
)
from server.db.vector_store import VectorStore, load_qa_data
from server.db.hybrid_search import HybridSearchEngine, BM25Index
from server.services.groq_service import GroqService
from server.services.rag_service import RAGService
from server.evaluation.evaluator import RAGEvaluator
from server.ingestion.document_parser import DocumentParser
from server.ingestion.chunking import ContextEnrichedRecursiveChunker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Singletons initialized by lifespan in main.py
vector_store: Optional[VectorStore] = None
bm25_index: Optional[BM25Index] = None
hybrid_search: Optional[HybridSearchEngine] = None
groq_service: Optional[GroqService] = None
rag_service: Optional[RAGService] = None
evaluator: Optional[RAGEvaluator] = None

def get_rag_service() -> RAGService:
    if not rag_service:
        raise HTTPException(status_code=503, detail="RAG service is not initialized")
    return rag_service

def get_vector_store() -> VectorStore:
    if not vector_store:
        raise HTTPException(status_code=503, detail="Vector store is not initialized")
    return vector_store

def get_hybrid_search() -> HybridSearchEngine:
    if not hybrid_search:
        raise HTTPException(status_code=503, detail="Hybrid search engine is not initialized")
    return hybrid_search

def get_evaluator() -> RAGEvaluator:
    if not evaluator:
        raise HTTPException(status_code=503, detail="RAG evaluator is not initialized")
    return evaluator

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Verify operational status of Vector DB, BM25 index, and Groq LLM service."""
    try:
        count = vector_store.collection.count() if vector_store else 0
        vdb_status = "healthy" if count > 0 else "empty"
        
        is_groq_healthy = groq_service.check_health() if groq_service else False
        groq_status = "healthy" if is_groq_healthy else ("unconfigured" if not (groq_service and groq_service.is_configured()) else "unavailable")
        bm25_count = len(bm25_index.corpus_ids) if bm25_index else 0

        return HealthResponse(
            status="healthy" if (count > 0 and is_groq_healthy) else "degraded",
            vector_database_status=vdb_status,
            vector_database_count=count,
            groq_status=groq_status,
            groq_model=groq_service.model if groq_service else os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            hybrid_search_enabled=os.getenv("ENABLE_BM25", "true").lower() == "true" and os.getenv("ENABLE_RERANKER", "true").lower() == "true",
            bm25_count=bm25_count,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats", response_model=StatsResponse, tags=["Statistics"])
async def get_stats(vdb: VectorStore = Depends(get_vector_store)):
    """Fetch vector database document statistics and metadata metrics."""
    try:
        stats = vdb.get_stats()
        return StatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to fetch stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest, rag: RAGService = Depends(get_rag_service)):
    """Process legal query through Self-Querying, Hybrid Retrieval (BM25 + Dense + RRF + Cross-Encoder), and Groq Llama-70B."""
    try:
        logger.info(f"Received query: '{request.query[:80]}...'")
        result = rag.query(
            query=request.query,
            top_k=request.top_k or 5,
            conversation_id=request.conversation_id,
            enable_rerank=request.enable_rerank if request.enable_rerank is not None else True,
        )
        return ChatResponse(**result)
    except Exception as e:
        logger.error(f"Chat processing error: {e}")
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")

@router.post("/chat/stream", tags=["Chat"])
async def chat_stream(request: ChatRequest, rag: RAGService = Depends(get_rag_service)):
    """Stream legal analysis token-by-token using Server-Sent Events (SSE)."""
    try:
        logger.info(f"Streaming query: '{request.query[:80]}...'")
        def event_stream():
            for event in rag.query_stream(
                query=request.query,
                top_k=request.top_k or 5,
                conversation_id=request.conversation_id,
                enable_rerank=request.enable_rerank if request.enable_rerank is not None else True,
            ):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.error(f"Streaming chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")

@router.get("/search", response_model=SearchResponse, tags=["Search"])
@router.post("/search", response_model=SearchResponse, tags=["Search"])
async def search_documents(
    query: str = Query(..., min_length=1, description="Search query string"),
    top_k: int = Query(5, ge=1, le=20, description="Max documents to return"),
    enable_rerank: bool = Query(True, description="Enable Cross-Encoder re-ranking"),
    hybrid: HybridSearchEngine = Depends(get_hybrid_search),
):
    """Multi-Stage Hybrid Search (Dense + BM25 + RRF + Cross-Encoder) supporting GET and POST."""
    try:
        candidates = hybrid.search(query=query, top_k=top_k, enable_rerank=enable_rerank)

        documents = []
        for c in candidates:
            meta = c.get("metadata", {})
            documents.append({
                "id": str(c.get("id")),
                "instruction": meta.get("instruction"),
                "response": meta.get("response"),
                "content_preview": c.get("content", "")[:400] + "..." if len(c.get("content", "")) > 400 else c.get("content", ""),
                "score": float(c.get("rerank_score") or c.get("similarity") or c.get("score") or 0.0),
                "retriever": c.get("retriever", "hybrid"),
            })

        return SearchResponse(
            query=query,
            results=documents,
            count=len(documents),
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/doc/{doc_id}", response_model=DocumentResponse, tags=["Documents"])
async def get_document(doc_id: str, vdb: VectorStore = Depends(get_vector_store)):
    """Fetch stored document details by normalized ID (e.g., '0' or 'qa_0')."""
    try:
        lookup_id = doc_id if doc_id.startswith("qa_") else f"qa_{doc_id}"
        result = vdb.collection.get(ids=[lookup_id])

        if not result or not result.get("ids"):
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

        doc_text = result["documents"][0] if result.get("documents") and len(result["documents"]) > 0 else None
        doc_meta = result["metadatas"][0] if result.get("metadatas") and len(result["metadatas"]) > 0 else None

        return DocumentResponse(
            id=result["ids"][0],
            document=doc_text,
            metadata=doc_meta,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching document '{doc_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/build-db", tags=["Admin"])
async def build_database(
    req: BuildRequest,
    vdb: VectorStore = Depends(get_vector_store),
    hybrid: HybridSearchEngine = Depends(get_hybrid_search),
):
    """Batch-index legal dataset into ChromaDB and build BM25 sparse index."""
    try:
        if req.reset:
            vdb.reset_database()

        data = load_qa_data(req.filename)
        if not data:
            raise HTTPException(status_code=404, detail=f"Source file '{req.filename}' not found in data/raw")

        if req.max_items:
            data = data[: req.max_items]

        # 1. Index in ChromaDB
        vdb.add_documents(data, batch_size=100)

        # 2. Build BM25 index
        if req.build_bm25:
            bm25_records = []
            for item in data:
                doc_id = f"qa_{item['id']}"
                content = f"Question: {item['Instruction']}\n\nAnswer: {item['Response']}"
                bm25_records.append({
                    "id": doc_id,
                    "content": content,
                    "metadata": {
                        "id": str(item["id"]),
                        "instruction": item["Instruction"][:500],
                        "response": item["Response"][:500],
                        "title": item["Instruction"][:70],
                    },
                })
            hybrid.bm25_index.build_index(bm25_records)

        return {
            "status": "ok",
            "added_to_vector_db": len(data),
            "total_in_vector_db": vdb.collection.count(),
            "total_in_bm25": len(hybrid.bm25_index.corpus_ids),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database build error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluate", response_model=EvaluateResponse, tags=["Evaluation"])
async def run_evaluation(
    req: EvaluateRequest = EvaluateRequest(),
    eval_service: RAGEvaluator = Depends(get_evaluator),
):
    """Execute automated benchmark evaluation measuring Recall@K, MRR, Precision, Faithfulness, and Answer Relevance."""
    try:
        logger.info("Executing RAG benchmark evaluation...")
        result = eval_service.evaluate_benchmark(
            top_k=req.top_k or 5,
            evaluate_generation=req.evaluate_generation if req.evaluate_generation is not None else True,
        )
        return EvaluateResponse(**result)
    except Exception as e:
        logger.error(f"Evaluation benchmark failed: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation execution failure: {str(e)}")

@router.post("/documents/upload", response_model=DocumentUploadResponse, tags=["Documents"])
async def upload_document(
    file: UploadFile = File(..., description="Legal PDF, TXT, or MD document"),
    category: str = Form("User Upload", description="Legal domain category"),
    vdb: VectorStore = Depends(get_vector_store),
    hybrid: HybridSearchEngine = Depends(get_hybrid_search),
):
    """Dynamically parse, chunk, and index legal brief, FIR, contract, or petition (PDF/TXT/MD)."""
    try:
        filename = file.filename or "uploaded_document.txt"
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # 1. Parse document text
        parsed = DocumentParser.parse_file(file_bytes, filename)

        # 2. Generate unique doc_id
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"

        # 3. Chunk text with context enrichment
        chunker = ContextEnrichedRecursiveChunker()
        chunks = chunker.chunk_raw_document(
            doc_id=doc_id,
            title=parsed["title"],
            text=parsed["text"],
            doc_type=parsed["doc_type"],
            category=category,
        )

        if not chunks:
            raise HTTPException(status_code=400, detail="No readable text extracted from document.")

        # 4. Insert into Vector DB (ChromaDB)
        vdb.add_chunks(chunks)

        # 5. Append to BM25 sparse index
        hybrid.bm25_index.add_records(chunks)

        logger.info(f"Successfully processed and indexed uploaded document '{filename}' ({len(chunks)} chunks).")
        return DocumentUploadResponse(
            status="success",
            filename=filename,
            document_id=doc_id,
            title=parsed["title"],
            doc_type=parsed["doc_type"],
            total_pages=parsed["page_count"],
            char_count=parsed["char_count"],
            chunks_created=len(chunks),
            total_in_vector_db=vdb.collection.count(),
            total_in_bm25=len(hybrid.bm25_index.corpus_ids),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document upload and indexing failed for {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process and index document: {str(e)}")

