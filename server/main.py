from contextlib import asynccontextmanager
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Ensure repository root is on sys.path for direct python execution
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load environment variables
load_dotenv(dotenv_path=CURRENT_DIR / ".env")
load_dotenv(dotenv_path=REPO_ROOT / ".env")

# Direct data directory paths
DATA_DIR = CURRENT_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
VECTOR_DB_DIR = Path(os.getenv("VECTOR_DB_PATH", str(DATA_DIR / "vectordb")))
BM25_INDEX_DIR = DATA_DIR / "bm25"
STATIC_DIR = CURRENT_DIR / "static"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
BM25_INDEX_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

from server.db.vector_store import VectorStore
from server.db.hybrid_search import BM25Index, CrossEncoderReranker, HybridSearchEngine
from server.services.groq_service import GroqService
from server.services.self_query_service import SelfQueryService
from server.services.rag_service import RAGService
from server.evaluation.evaluator import RAGEvaluator
import server.api.routes as routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kanoon.server")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to initialize and teardown singletons."""
    logger.info("Starting up कानून (Kanoon) AI Legal Assistant API with Advanced Hybrid RAG...")
    
    # 1. Initialize VectorStore (Dense Embeddings)
    routes.vector_store = VectorStore(
        persist_directory=VECTOR_DB_DIR,
        embedding_model_name=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        collection_name=os.getenv("VECTOR_DB_COLLECTION", "legal_qa"),
    )

    # 2. Initialize BM25 Sparse Index
    routes.bm25_index = BM25Index(
        persist_path=BM25_INDEX_DIR / "bm25_store.pkl"
    )

    # 3. Initialize Cross-Encoder Re-ranker
    enable_rerank = os.getenv("ENABLE_RERANKER", "true").lower() == "true"
    reranker = CrossEncoderReranker(
        model_name=os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    ) if enable_rerank else None

    # 4. Initialize Hybrid Search Engine (Dense + Sparse + RRF + Cross-Encoder)
    routes.hybrid_search = HybridSearchEngine(
        vector_store=routes.vector_store,
        bm25_index=routes.bm25_index,
        reranker=reranker,
        rrf_k=int(os.getenv("RRF_K", "60")),
    )
    
    # 5. Initialize GroqService
    routes.groq_service = GroqService(
        api_key=os.getenv("GROQ_API_KEY", ""),
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    )

    # 6. Initialize Self-Querying Legal Reformulation Service
    self_query_service = SelfQueryService(groq_service=routes.groq_service)

    # 7. Initialize Advanced RAGService
    routes.rag_service = RAGService(
        vector_store=routes.vector_store,
        groq_service=routes.groq_service,
        hybrid_search_engine=routes.hybrid_search,
        self_query_service=self_query_service,
        relevance_threshold=float(os.getenv("RELEVANCE_THRESHOLD", "0.35")),
    )

    # 8. Initialize RAG Benchmark Evaluator
    routes.evaluator = RAGEvaluator(
        rag_service=routes.rag_service
    )
    
    logger.info("All Advanced RAG components, Hybrid Search, and Evaluator successfully initialized.")
    yield
    logger.info("Shutting down Kanoon API server...")

app_title = os.getenv("APP_TITLE", "कानून (Kanoon) - AI Legal Assistant API")
app_version = "2.2.0"
groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

app = FastAPI(
    title=app_title,
    description="API for querying Indian Constitution, legal precedents, and procedural codes using Groq Llama-70B, ChromaDB, and Advanced Hybrid RAG",
    version=app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Include API Router
app.include_router(routes.router)

# Mount static asset directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", tags=["UI"])
async def serve_ui():
    """Serve the Kanoon AI Legal Assistant web application."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "service": app_title,
        "version": app_version,
        "docs": "/docs",
    }

@app.get("/api", tags=["Root"])
@app.get("/info", tags=["Root"])
async def root():
    """Root endpoint providing service information and links."""
    return {
        "service": app_title,
        "version": app_version,
        "model": groq_model,
        "features": [
            "Streaming Token Delivery (SSE)",
            "Bar Council Compliance & Legal Guardrails",
            "Indic Multi-Lingual Support (Hindi / Hinglish)",
            "Dynamic Document & Contract Upload (PDF/TXT/MD)",
            "Self-Querying Legal Reformulation",
            "Context-Enriched Recursive Chunking",
            "Hybrid Search (Dense + BM25)",
            "Reciprocal Rank Fusion (RRF)",
            "Cross-Encoder Re-ranking",
            "RAG Evaluation Suite (Recall@K, MRR, Faithfulness, Relevance)",
        ],
        "docs": "/docs",
        "health": "/api/health",
        "stats": "/api/stats",
        "evaluate": "/api/evaluate",
    }

if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
