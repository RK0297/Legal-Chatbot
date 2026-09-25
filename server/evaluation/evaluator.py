"""End-to-end RAG Evaluation Benchmark Runner for Kanoon Legal Assistant."""
from typing import Dict, List, Optional
import logging
from datetime import datetime

from server.evaluation.metrics import calculate_recall_at_k, calculate_precision_at_k, calculate_mrr
from server.evaluation.llm_judge import LLMJudge
from server.services.rag_service import RAGService

logger = logging.getLogger(__name__)

# Curated benchmark dataset of representative Indian legal inquiries
DEFAULT_LEGAL_BENCHMARK = [
    {
        "id": "bench_0",
        "question": "What is the difference between a petition and a plaint in Indian law?",
        "expected_ids": ["qa_0"],
        "category": "Civil Procedure",
    },
    {
        "id": "bench_1",
        "question": "When should a writ petition be filed in India and what are common examples?",
        "expected_ids": ["qa_1"],
        "category": "Constitutional Law",
    },
    {
        "id": "bench_2",
        "question": "What is the procedure for filing a plaint in a civil case in India?",
        "expected_ids": ["qa_2"],
        "category": "Civil Procedure",
    },
    {
        "id": "bench_3",
        "question": "What are the common reliefs sought through a public interest litigation (PIL) in India?",
        "expected_ids": ["qa_3"],
        "category": "Public Interest Law",
    },
    {
        "id": "bench_4",
        "question": "Can a plaint be amended after filing in a civil case in India?",
        "expected_ids": ["qa_4"],
        "category": "Civil Procedure",
    },
]

class RAGEvaluator:
    """Runs automated retrieval and generation evaluations against benchmark test suites."""

    def __init__(self, rag_service: RAGService, llm_judge: Optional[LLMJudge] = None):
        self.rag_service = rag_service
        self.llm_judge = llm_judge or LLMJudge(groq_service=rag_service.groq_service)

    def evaluate_benchmark(
        self,
        benchmark_cases: Optional[List[Dict]] = None,
        top_k: int = 5,
        evaluate_generation: bool = True,
    ) -> Dict:
        """Run complete evaluation over benchmark cases and compute Recall@K, MRR, Precision, Faithfulness, Relevance."""
        cases = benchmark_cases or DEFAULT_LEGAL_BENCHMARK
        logger.info(f"Running RAG evaluation across {len(cases)} benchmark cases (top_k={top_k})...")

        retrieval_records: List[Dict] = []
        all_retrieved_ids: List[List[str]] = []
        all_expected_ids: List[List[str]] = []

        faithfulness_scores: List[float] = []
        relevance_scores: List[float] = []

        for case in cases:
            q_id = case["id"]
            question = case["question"]
            expected = case.get("expected_ids", [])
            all_expected_ids.append(expected)

            # Execute RAG query
            query_res = self.rag_service.query(query=question, top_k=top_k)
            retrieved_sources = query_res.get("sources", [])
            
            # Extract retrieved doc IDs
            retrieved_ids = []
            for src in retrieved_sources:
                # Preview or title may contain ID
                retrieved_ids.append(src.get("title", ""))

            # Also check candidate IDs from retrieval
            retrieval_debug = self.rag_service.retrieve_context(question, top_k=top_k)
            candidate_ids = [c.get("id", "") for c in retrieval_debug.get("candidates", [])]
            all_retrieved_ids.append(candidate_ids)

            # Compute per-query IR metrics
            r_at_3 = calculate_recall_at_k(candidate_ids, expected, k=3)
            r_at_5 = calculate_recall_at_k(candidate_ids, expected, k=5)
            p_at_3 = calculate_precision_at_k(candidate_ids, expected, k=3)
            p_at_5 = calculate_precision_at_k(candidate_ids, expected, k=5)

            # Optional Generation Evaluation
            faith_result = {"score": 1.0, "reasoning": "Skipped"}
            rel_result = {"score": 1.0, "reasoning": "Skipped"}

            if evaluate_generation and self.rag_service.groq_service.is_configured():
                combined_context = "\n".join([s.get("preview", "") for s in retrieved_sources])
                faith_result = self.llm_judge.evaluate_faithfulness(
                    question=question,
                    context=combined_context,
                    answer=query_res["response"],
                )
                rel_result = self.llm_judge.evaluate_answer_relevance(
                    question=question,
                    answer=query_res["response"],
                )
                faithfulness_scores.append(faith_result["score"])
                relevance_scores.append(rel_result["score"])

            retrieval_records.append({
                "case_id": q_id,
                "question": question,
                "expected_ids": expected,
                "retrieved_ids": candidate_ids,
                "recall_at_3": r_at_3,
                "recall_at_5": r_at_5,
                "precision_at_3": p_at_3,
                "precision_at_5": p_at_5,
                "faithfulness": faith_result,
                "answer_relevance": rel_result,
            })

        # Aggregate Metrics
        overall_mrr = calculate_mrr(all_retrieved_ids, all_expected_ids)
        avg_recall_3 = sum(r["recall_at_3"] for r in retrieval_records) / len(retrieval_records)
        avg_recall_5 = sum(r["recall_at_5"] for r in retrieval_records) / len(retrieval_records)
        avg_precision_3 = sum(r["precision_at_3"] for r in retrieval_records) / len(retrieval_records)
        avg_precision_5 = sum(r["precision_at_5"] for r in retrieval_records) / len(retrieval_records)

        avg_faithfulness = (
            sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 1.0
        )
        avg_relevance = (
            sum(relevance_scores) / len(relevance_scores) if relevance_scores else 1.0
        )

        return {
            "evaluation_timestamp": datetime.now().isoformat(),
            "total_benchmark_cases": len(cases),
            "aggregate_metrics": {
                "mrr": round(overall_mrr, 4),
                "recall_at_3": round(avg_recall_3, 4),
                "recall_at_5": round(avg_recall_5, 4),
                "precision_at_3": round(avg_precision_3, 4),
                "precision_at_5": round(avg_precision_5, 4),
                "avg_faithfulness": round(avg_faithfulness, 4),
                "avg_answer_relevance": round(avg_relevance, 4),
            },
            "detailed_case_results": retrieval_records,
        }
