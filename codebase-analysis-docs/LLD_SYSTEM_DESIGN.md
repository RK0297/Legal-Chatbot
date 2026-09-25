# Low-Level Design (LLD): Kanoon (कानून) - AI Legal Assistant

## 1. Class Structure & Component Hierarchy

```mermaid
classDiagram
    class RAGService {
        +VectorStore vector_store
        +GroqService groq_service
        +HybridSearchEngine hybrid_search
        +SelfQueryService self_query
        +LegalGuardrails guardrails
        +float relevance_threshold
        +dict conversations
        +retrieve_context(query, top_k, enable_rerank) dict
        +build_system_prompt(candidates, use_rag, detected_language) str
        +query(query, top_k, conversation_id, enable_rerank) dict
        +query_stream(query, top_k, conversation_id, enable_rerank) Generator
    }

    class LegalGuardrails {
        +float relevance_threshold
        +detect_emergency(query) Optional~dict~
        +format_emergency_banner(emergency_info) str
        +evaluate_confidence(candidates, threshold) tuple~bool, Optional~str~~
        +attach_disclaimer(response_text) str
    }

    class SelfQueryService {
        +GroqService groq_service
        +reformulate_and_extract(user_query) dict
    }

    class HybridSearchEngine {
        +VectorStore vector_store
        +BM25Index bm25_index
        +CrossEncoderReranker reranker
        +int rrf_k
        +reciprocal_rank_fusion(dense, sparse, limit) list
        +search(query, top_k, dense_limit, sparse_limit, enable_rerank, filter_dict) list
    }

    class BM25Index {
        +Path persist_path
        +BM25Okapi bm25
        +list corpus_ids
        +list corpus_docs
        +list corpus_metas
        +build_index(records)
        +add_records(records)
        +search(query, top_k) list
        +save()
        +load_if_exists() bool
    }

    class VectorStore {
        +str collection_name
        +str model_name
        +PersistentClient client
        +Collection collection
        +SentenceTransformer embedding_model
        +generate_embeddings(texts) list
        +add_documents(qa_pairs, batch_size)
        +add_chunks(chunks, batch_size)
        +search(query, n_results, filter_dict) dict
        +get_stats() dict
    }

    class DocumentParser {
        +parse_pdf_bytes(file_bytes, filename)$ dict
        +parse_text_bytes(file_bytes, filename)$ dict
        +parse_file(file_bytes, filename)$ dict
    }

    class ContextEnrichedRecursiveChunker {
        +int chunk_size
        +int chunk_overlap
        +list separators
        +_split_text(text, separators) list
        +chunk_document(qa_record) list
        +chunk_raw_document(doc_id, title, text, doc_type, category) list
    }

    class GroqService {
        +str api_key
        +str model
        +Groq _groq_client
        +is_configured() bool
        +check_health() bool
        +generate_chat_completion(messages, temperature, max_tokens) str
        +chat_completion_stream(messages, temperature, max_tokens) Generator
    }

    RAGService --> LegalGuardrails
    RAGService --> SelfQueryService
    RAGService --> HybridSearchEngine
    RAGService --> GroqService
    HybridSearchEngine --> VectorStore
    HybridSearchEngine --> BM25Index
```

---

## 2. Sequence Diagrams

### 2.1 Streaming Token Lifecycle (`POST /api/chat/stream`)

```mermaid
sequenceDiagram
    autonumber
    actor User as Client / Web UI
    participant Route as FastAPI (/api/chat/stream)
    participant RAG as RAGService
    participant Guard as LegalGuardrails
    participant SQ as SelfQueryService
    participant Hybrid as HybridSearchEngine
    participant Groq as Groq Cloud LPU

    User->>Route: POST /api/chat/stream (query, conversation_id)
    Route->>RAG: query_stream(query)
    RAG->>Guard: detect_emergency(query)
    Guard-->>RAG: emergency_alert (or None)
    
    RAG->>SQ: reformulate_and_extract(query)
    SQ-->>RAG: {reformulated_query, keywords, detected_language}
    
    RAG->>Hybrid: search(reformulated_query, top_k=5)
    Hybrid-->>RAG: ranked_candidates
    
    RAG-->>Route: yield SSE event: metadata (citations, urgency, search_query)
    Route-->>User: data: {"type": "metadata", ...}
    
    opt Emergency Detected
        RAG->>Guard: format_emergency_banner(emergency_alert)
        Guard-->>RAG: emergency_banner
        RAG-->>Route: yield SSE event: token (banner text)
        Route-->>User: data: {"type": "token", "delta": "🚨 URGENT..."}
    end

    RAG->>Groq: chat_completion_stream(prompt_messages)
    loop Token Streaming
        Groq-->>RAG: token delta
        RAG-->>Route: yield SSE event: token
        Route-->>User: data: {"type": "token", "delta": token}
    end

    RAG-->>Route: yield SSE event: token (Bar Council Disclaimer)
    Route-->>User: data: {"type": "token", "delta": "⚖️ Statutory Disclaimer..."}

    RAG-->>Route: yield SSE event: done
    Route-->>User: data: {"type": "done", "conversation_id": "..."}
```

---

### 2.2 Dynamic Document Ingestion Lifecycle (`POST /api/documents/upload`)

```mermaid
sequenceDiagram
    autonumber
    actor User as Advocate / Citizen
    participant Route as FastAPI (/api/documents/upload)
    participant Parser as DocumentParser
    participant Chunker as ContextEnrichedChunker
    participant VDB as VectorStore (ChromaDB)
    participant BM25 as BM25Index

    User->>Route: POST /api/documents/upload (file: petition.pdf, category)
    Route->>Parser: parse_file(bytes, filename)
    Parser-->>Route: {title, text, page_count, doc_type}
    
    Route->>Chunker: chunk_raw_document(doc_id, title, text, doc_type)
    Chunker-->>Route: enriched_chunks [chunk_0, chunk_1, ...]
    
    Route->>VDB: add_chunks(enriched_chunks)
    VDB->>VDB: generate_embeddings() -> ChromaDB insert
    
    Route->>BM25: add_records(enriched_chunks)
    BM25->>BM25: tokenize -> refresh BM25Okapi -> pickle save
    
    Route-->>User: DocumentUploadResponse (status="success", chunks_created=N, total_in_db=M)
```

---

## 3. Data Schemas & API Contracts

### 3.1 Pydantic Request & Response Models

#### `ChatRequest`
```python
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    conversation_id: Optional[str] = None
    top_k: Optional[int] = 5
    enable_rerank: Optional[bool] = True
```

#### `ChatResponse`
```python
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
```

#### `DocumentUploadResponse`
```python
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
```

---

## 4. Error Handling & Resilience Matrix

| Failure Mode | Detection Point | Handling Strategy | User Experience |
| :--- | :--- | :--- | :--- |
| **Groq API Key Unset** | `GroqService.is_configured()` | Emits explicit configuration guidance | Warns user to set key in `.env`; retrieval still succeeds |
| **Groq Network Timeout** | `requests.exceptions.Timeout` | 60-second cutoff with graceful catch | "Response generation timed out, please retry." |
| **Corrupted PDF Upload** | `DocumentParser.parse_pdf_bytes()` | Dual parser attempt: PyPDF -> PyMuPDF (fitz) | HTTP 400 with actionable formatting detail |
| **Low Confidence Precedent** | `LegalGuardrails.evaluate_confidence()` | Cross-encoder score < -2.0 | Emits cautious non-hallucinatory guidance + NALSA helpline |
| **Out-of-Memory Embedding** | `VectorStore.add_chunks()` | Batch size fixed at 100 with progress slicing | Transparent ingestion without server crash |
