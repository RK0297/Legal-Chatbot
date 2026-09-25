import os
import uuid
import logging
from typing import Dict, List, Optional, Generator
from datetime import datetime

from server.db.vector_store import VectorStore
from server.db.hybrid_search import HybridSearchEngine
from server.services.groq_service import GroqService
from server.services.self_query_service import SelfQueryService
from server.services.guardrails import LegalGuardrails, BAR_COUNCIL_DISCLAIMER

logger = logging.getLogger(__name__)

class RAGService:
    """Orchestrates Advanced Hybrid Retrieval-Augmented Generation using Groq Llama-70B."""

    def __init__(
        self,
        vector_store: VectorStore,
        groq_service: GroqService,
        hybrid_search_engine: Optional[HybridSearchEngine] = None,
        self_query_service: Optional[SelfQueryService] = None,
        relevance_threshold: Optional[float] = None,
    ):
        self.vector_store = vector_store
        self.groq_service = groq_service
        self.hybrid_search = hybrid_search_engine or HybridSearchEngine(vector_store=vector_store)
        self.self_query = self_query_service or SelfQueryService(groq_service=groq_service)
        self.relevance_threshold = relevance_threshold if relevance_threshold is not None else float(os.getenv("RELEVANCE_THRESHOLD", "0.35"))
        self.guardrails = LegalGuardrails(relevance_threshold=self.relevance_threshold)
        self.conversations: Dict[str, List[Dict[str, str]]] = {}

        logger.info(
            f"Advanced RAGService initialized with model '{groq_service.model}', "
            f"relevance threshold {self.relevance_threshold}, Guardrails active, and Hybrid Search enabled."
        )

    def retrieve_context(
        self,
        query: str,
        top_k: int = 5,
        enable_rerank: bool = True,
    ) -> Dict:
        """Execute Self-Querying followed by Multi-Stage Hybrid Retrieval."""
        # 1. Self-Query Legal Reformulation
        sq_result = self.self_query.reformulate_and_extract(query)
        search_query = sq_result["reformulated_query"]
        category_filter = {"category": sq_result["category"]} if sq_result.get("category") else None

        # 2. Multi-Stage Hybrid Search (Dense + BM25 + RRF + Cross-Encoder)
        candidates = self.hybrid_search.search(
            query=search_query,
            top_k=top_k,
            enable_rerank=enable_rerank,
            filter_dict=category_filter,
        )

        return {
            "search_query": search_query,
            "keywords": sq_result.get("keywords", []),
            "detected_language": sq_result.get("detected_language", "English"),
            "candidates": candidates,
        }

    def get_attached_document(self, document_id: str) -> Optional[Dict]:
        """Retrieve chunks and metadata for an attached document from vector store."""
        if not document_id:
            return None
        try:
            res = self.vector_store.collection.get(where={"id": document_id})
            if res and res.get("documents") and len(res["documents"]) > 0:
                docs = res["documents"]
                metas = res.get("metadatas", [])
                title = metas[0].get("title", "Attached Document") if metas else "Attached Document"
                doc_type = metas[0].get("doc_type", "Document") if metas else "PDF"
                combined_text = "\n\n".join(docs)
                return {
                    "document_id": document_id,
                    "title": title,
                    "doc_type": doc_type,
                    "content": combined_text,
                    "chunk_count": len(docs),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch attached document context for {document_id}: {e}")
        return None

    def build_system_prompt(
        self,
        context_candidates: List[Dict],
        use_rag: bool = True,
        detected_language: str = "English",
        attached_doc: Optional[Dict] = None,
    ) -> str:
        """Construct system persona, context prompt, and language directives."""
        if use_rag or attached_doc:
            system_prompt = (
                "You are कानून (Kanoon), an authoritative AI legal assistant specializing in Indian jurisprudence, "
                "the Constitution of India, Bharatiya Nyaya Sanhita (BNS / IPC), Bharatiya Nagarik Suraksha Sanhita (BNSS / CrPC), "
                "Code of Civil Procedure (CPC), and landmark High Court / Supreme Court precedents.\n\n"
                "Operational Guidelines:\n"
                "1. Answer clearly, authoritatively, and comprehensively in a structured, conversational manner.\n"
                "2. Ground your legal assertions directly on the provided statutory precedents and/or attached document.\n"
                "3. Cite Reference IDs (e.g., [Reference 1]) when referencing specific principles, acts, or procedures.\n"
                "4. Maintain strict statutory accuracy while keeping explanations accessible to citizens.\n"
                "5. Remind users that this consultation provides legal information and does not constitute an attorney-client relationship.\n\n"
            )

            if attached_doc:
                system_prompt += (
                    f"--- USER ATTACHED DOCUMENT: {attached_doc['title']} ({attached_doc['doc_type']}) ---\n"
                    f"{attached_doc['content'][:8000]}\n"
                    f"--- END OF ATTACHED DOCUMENT ---\n\n"
                    f"ATTACHED DOCUMENT INSTRUCTIONS:\n"
                    f"- The user attached '{attached_doc['title']}'. Analyze this document directly in response to the user's inquiry.\n"
                    f"- Cite specific clauses, terms, or sections from the attached text where applicable.\n"
                    f"- Cross-reference the document with applicable Indian statutory laws and regulations.\n\n"
                )

            if context_candidates:
                system_prompt += "--- CONTEXT FROM INDIAN LEGAL PRECEDENTS DATABASE ---\n"
                for i, item in enumerate(context_candidates, 1):
                    meta = item.get("metadata", {})
                    doc_id = item.get("id") or meta.get("id", str(i))
                    instruction = meta.get("instruction", "")
                    response = meta.get("response", "")
                    content = item.get("content", "")

                    if instruction and response:
                        system_prompt += (
                            f"\n[Reference {i}] (ID: {doc_id}):\n"
                            f"Legal Query: {instruction}\n"
                            f"Statutory Answer: {response}\n"
                        )
                    else:
                        system_prompt += f"\n[Reference {i}] (ID: {doc_id}):\n{content}\n"

                system_prompt += "\n--- END OF CONTEXT ---\n"
        else:
            system_prompt = (
                "You are कानून (Kanoon), an expert AI legal assistant with deep knowledge of Indian law and constitutional doctrines.\n\n"
                "Guidelines:\n"
                "1. Answer clearly, authoritatively, and comprehensively using your general legal knowledge.\n"
                "2. Structure explanations with relevant articles, sections, and foundational legal principles.\n"
                "3. Use simple language while maintaining strict legal accuracy.\n"
                "4. Explicitly inform the user that this response is derived from general Indian legal principles "
                "because no specific precedent met the database similarity threshold for their query.\n"
                "5. Remind users that this is for educational purposes and not a substitute for formal legal counsel.\n"
            )

        if detected_language == "Hindi":
            system_prompt += (
                "\n--- LANGUAGE DIRECTIVE (HINDI) ---\n"
                "The citizen has asked their question in Hindi. You MUST formulate your entire response in clear, polite Hindi (Devanagari script).\n"
                "Retain relevant Act names, section numbers, and legal citations in both Devanagari and English for clarity (e.g., 'धारा 138 (Section 138, NI Act)').\n"
            )
        elif detected_language == "Hinglish":
            system_prompt += (
                "\n--- LANGUAGE DIRECTIVE (HINGLISH) ---\n"
                "The citizen has communicated in Hinglish (Hindi written in Roman / English alphabets).\n"
                "You MUST formulate your complete response in natural, respectful Hinglish that is easy for a common citizen to understand, "
                "while clearly citing exact statutory provisions, section numbers, and legal steps (e.g., 'Section 138 NI Act ke tehat legal notice bhejna padega').\n"
            )

        return system_prompt

    def get_conversation_history(self, conversation_id: str) -> List[Dict[str, str]]:
        return self.conversations.get(conversation_id, [])

    def update_conversation_history(
        self,
        conversation_id: str,
        user_query: str,
        assistant_response: str,
    ):
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []

        self.conversations[conversation_id].append({"role": "user", "content": user_query})
        self.conversations[conversation_id].append({"role": "assistant", "content": assistant_response})

        if len(self.conversations[conversation_id]) > 10:
            self.conversations[conversation_id] = self.conversations[conversation_id][-10:]

    def query(
        self,
        query: str,
        top_k: int = 5,
        conversation_id: Optional[str] = None,
        enable_rerank: bool = True,
        document_id: Optional[str] = None,
    ) -> Dict:
        """Execute full Advanced Hybrid RAG query cycle with Groq Llama-70B."""
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Step 0: Check for user-attached document
        attached_doc = self.get_attached_document(document_id) if document_id else None

        # Step 1: Self-Query & Multi-Stage Hybrid Retrieval
        retrieval_output = self.retrieve_context(query, top_k=top_k, enable_rerank=enable_rerank)
        candidates = retrieval_output["candidates"]
        detected_lang = retrieval_output.get("detected_language", "English")

        # Step 2: Emergency Helpline Detection
        emergency_alert = self.guardrails.detect_emergency(query)

        # Step 3: Relevance Assessment & Mode Selection
        use_rag = False
        avg_score = 0.0

        if candidates:
            scores = []
            for c in candidates:
                if "rerank_score" in c:
                    scores.append(c["rerank_score"])
                elif "similarity" in c:
                    scores.append(c["similarity"])
                else:
                    scores.append(0.5)

            avg_score = sum(scores) / len(scores) if scores else 0.0
            use_rag = len(candidates) > 0

        if attached_doc:
            use_rag = True

        mode = "advanced_rag" if use_rag else "llm"
        logger.info(f"Query Mode: {mode.upper()} [{detected_lang}] (Attached: {bool(attached_doc)}, Retrieved: {len(candidates)} items, Avg Score: {avg_score:.3f})")

        # Step 4: Prompt Construction
        system_content = self.build_system_prompt(
            context_candidates=candidates if use_rag else [],
            use_rag=use_rag,
            detected_language=detected_lang,
            attached_doc=attached_doc,
        )

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_content}]

        history = self.get_conversation_history(conversation_id)
        if history:
            messages.extend(history[-6:])

        messages.append({"role": "user", "content": query})

        # Step 5: Generation via Groq
        response_text = self.groq_service.generate_chat_completion(
            messages=messages,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1500")),
        )

        # Step 6: Guardrails Enforcement (Emergency banner + Statutory disclaimer)
        if emergency_alert:
            emergency_banner = self.guardrails.format_emergency_banner(emergency_alert)
            response_text = emergency_banner + response_text

        response_text = self.guardrails.attach_disclaimer(response_text)

        # Step 7: Update Session History
        self.update_conversation_history(conversation_id, query, response_text)

        # Step 8: Format Sources
        sources = []
        if attached_doc:
            sources.append({
                "title": f"Attached: {attached_doc['title']}",
                "source": f"{attached_doc['doc_type']} ({attached_doc['chunk_count']} sections)",
                "category": "User Uploaded Document",
                "url": "",
                "preview": attached_doc["content"][:280] + "..." if len(attached_doc["content"]) > 280 else attached_doc["content"],
                "retriever": "attached_document",
                "score": 1.0,
            })

        if use_rag:
            for item in candidates:
                meta = item.get("metadata", {})
                doc_text = item.get("content", "")
                sources.append({
                    "title": meta.get("title", f"Legal Precedent #{item.get('id', 'N/A')}"),
                    "source": meta.get("source", "Indian Law Dataset"),
                    "category": meta.get("category", "Constitutional Law"),
                    "url": meta.get("url", ""),
                    "preview": doc_text[:250] + "..." if len(doc_text) > 250 else doc_text,
                    "retriever": item.get("retriever", "hybrid"),
                    "score": item.get("rerank_score") or item.get("similarity") or item.get("rrf_score"),
                })

        return {
            "response": response_text,
            "sources": sources,
            "conversation_id": conversation_id,
            "mode": mode,
            "search_query": retrieval_output.get("search_query", query),
            "similarity_score": avg_score,
            "emergency_alert": emergency_alert,
            "statutory_disclaimer": BAR_COUNCIL_DISCLAIMER.strip(),
            "detected_language": detected_lang,
            "timestamp": datetime.now().isoformat(),
        }

    def query_stream(
        self,
        query: str,
        top_k: int = 5,
        conversation_id: Optional[str] = None,
        enable_rerank: bool = True,
        document_id: Optional[str] = None,
    ) -> Generator[Dict, None, None]:
        """Stream conversational legal analysis token-by-token with Guardrails and Indic support.

        Yields:
            Dict events:
                - {"type": "metadata", ...} with citations, search query, mode, emergency alert
                - {"type": "token", "delta": str} for each text chunk (including emergency banner & disclaimer)
                - {"type": "done", "conversation_id": str, "timestamp": str}
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Step 0: Check for user-attached document
        attached_doc = self.get_attached_document(document_id) if document_id else None

        # Step 1: Self-Query & Multi-Stage Hybrid Retrieval
        retrieval_output = self.retrieve_context(query, top_k=top_k, enable_rerank=enable_rerank)
        candidates = retrieval_output["candidates"]
        detected_lang = retrieval_output.get("detected_language", "English")

        # Step 2: Emergency Detection
        emergency_alert = self.guardrails.detect_emergency(query)

        # Step 3: Relevance Assessment & Mode Selection
        use_rag = False
        avg_score = 0.0

        if candidates:
            scores = []
            for c in candidates:
                if "rerank_score" in c:
                    scores.append(c["rerank_score"])
                elif "similarity" in c:
                    scores.append(c["similarity"])
                else:
                    scores.append(0.5)
            avg_score = sum(scores) / len(scores) if scores else 0.0
            use_rag = len(candidates) > 0

        if attached_doc:
            use_rag = True

        mode = "advanced_rag" if use_rag else "llm"
        logger.info(f"Stream Query Mode: {mode.upper()} [{detected_lang}] (Attached: {bool(attached_doc)}, Retrieved: {len(candidates)} items, Avg Score: {avg_score:.3f})")

        # Step 4: Format Sources
        sources = []
        if attached_doc:
            sources.append({
                "title": f"Attached: {attached_doc['title']}",
                "source": f"{attached_doc['doc_type']} ({attached_doc['chunk_count']} sections)",
                "category": "User Uploaded Document",
                "url": "",
                "preview": attached_doc["content"][:280] + "..." if len(attached_doc["content"]) > 280 else attached_doc["content"],
                "retriever": "attached_document",
                "score": 1.0,
            })

        if use_rag:
            for item in candidates:
                meta = item.get("metadata", {})
                doc_text = item.get("content", "")
                sources.append({
                    "title": meta.get("title", f"Legal Precedent #{item.get('id', 'N/A')}"),
                    "source": meta.get("source", "Indian Law Dataset"),
                    "category": meta.get("category", "Constitutional Law"),
                    "url": meta.get("url", ""),
                    "preview": doc_text[:250] + "..." if len(doc_text) > 250 else doc_text,
                    "retriever": item.get("retriever", "hybrid"),
                    "score": item.get("rerank_score") or item.get("similarity") or item.get("rrf_score"),
                })

        # Yield metadata event first
        yield {
            "type": "metadata",
            "conversation_id": conversation_id,
            "sources": sources,
            "mode": mode,
            "search_query": retrieval_output.get("search_query", query),
            "similarity_score": avg_score,
            "emergency_alert": emergency_alert,
            "detected_language": detected_lang,
            "attached_document": {"title": attached_doc["title"], "doc_type": attached_doc["doc_type"]} if attached_doc else None,
            "timestamp": datetime.now().isoformat(),
        }

        # Step 5: Prompt Construction
        system_content = self.build_system_prompt(
            context_candidates=candidates if use_rag else [],
            use_rag=use_rag,
            detected_language=detected_lang,
            attached_doc=attached_doc,
        )

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_content}]
        history = self.get_conversation_history(conversation_id)
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": query})

        # Step 6: Stream tokens (Emergency Banner -> LLM tokens -> Disclaimer)
        full_tokens = []

        if emergency_alert:
            banner = self.guardrails.format_emergency_banner(emergency_alert)
            full_tokens.append(banner)
            yield {
                "type": "token",
                "delta": banner,
            }

        for token in self.groq_service.chat_completion_stream(
            messages=messages,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1500")),
        ):
            full_tokens.append(token)
            yield {
                "type": "token",
                "delta": token,
            }

        # Stream Bar Council disclaimer
        yield {
            "type": "token",
            "delta": BAR_COUNCIL_DISCLAIMER,
        }
        full_tokens.append(BAR_COUNCIL_DISCLAIMER)

        full_response = "".join(full_tokens)

        # Step 7: Update Session History
        self.update_conversation_history(conversation_id, query, full_response)

        # Step 8: Yield completion event
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
        }


