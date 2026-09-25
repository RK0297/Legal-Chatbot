from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="User legal query")
    conversation_id: Optional[str] = Field(None, description="Session ID for context continuation")
    top_k: Optional[int] = Field(5, ge=1, le=10, description="Number of legal documents to retrieve")
    enable_rerank: Optional[bool] = Field(True, description="Enable Cross-Encoder re-ranking")

class SourceItem(BaseModel):
    title: str
    source: str
    category: str
    url: str = ""
    preview: str
    retriever: Optional[str] = "hybrid"
    score: Optional[float] = None

class ChatResponse(BaseModel):
    response: str
    sources: List[SourceItem]
    conversation_id: str
    mode: str = "advanced_rag"
    search_query: Optional[str] = None
    similarity_score: Optional[float] = None
    emergency_alert: Optional[Dict] = None
    statutory_disclaimer: Optional[str] = None
    timestamp: str

class HealthResponse(BaseModel):
    status: str
    vector_database_status: str
    vector_database_count: int
    groq_status: str
    groq_model: str
    hybrid_search_enabled: bool = True
    bm25_count: int = 0
    timestamp: str

class StatsResponse(BaseModel):
    total_qa_pairs: int
    total_documents: int
    collection_name: str
    embedding_model: str
    categories: List[str]
    document_types: List[str]
    avg_instruction_length: Optional[int] = 0
    avg_response_length: Optional[int] = 0

class BuildRequest(BaseModel):
    reset: Optional[bool] = Field(False, description="Reset collection before indexing")
    max_items: Optional[int] = Field(None, description="Max records to index (for testing)")
    filename: Optional[str] = Field("legal_data_all.json", description="Source JSON file in server/data/raw")
    build_bm25: Optional[bool] = Field(True, description="Also build/update BM25 sparse index")

class SearchResultItem(BaseModel):
    id: Optional[str] = None
    instruction: Optional[str] = None
    response: Optional[str] = None
    content_preview: str
    score: Optional[float] = None
    retriever: Optional[str] = None

class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultItem]
    count: int

class DocumentResponse(BaseModel):
    id: str
    document: Optional[str] = None
    metadata: Optional[Dict] = None

class EvaluateRequest(BaseModel):
    top_k: Optional[int] = Field(5, ge=1, le=10, description="Top K for Recall and Precision evaluation")
    evaluate_generation: Optional[bool] = Field(True, description="Run LLM-as-a-judge for Faithfulness & Relevance")

class AggregateMetrics(BaseModel):
    mrr: float
    recall_at_3: float
    recall_at_5: float
    precision_at_3: float
    precision_at_5: float
    avg_faithfulness: float
    avg_answer_relevance: float

class EvaluateResponse(BaseModel):
    evaluation_timestamp: str
    total_benchmark_cases: int
    aggregate_metrics: AggregateMetrics
    detailed_case_results: List[Dict]

class DocumentUploadResponse(BaseModel):
    status: str
    filename: str
    document_id: str
    title: str
    doc_type: str
    total_pages: int
    char_count: int
    chunks_created: int
    total_in_vector_db: int
    total_in_bm25: int
    timestamp: str

