"""Information Retrieval Evaluation Metrics: Recall@K, MRR, Precision@K."""
from typing import List, Set

def calculate_recall_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int = 5) -> float:
    """Calculate Recall@K: fraction of ground-truth relevant documents retrieved in top-k.

    Args:
        retrieved_ids: Ordered list of document IDs returned by retriever.
        relevant_ids: List of ground-truth relevant document IDs.
        k: Cutoff rank.

    Returns:
        Recall score (0.0 to 1.0).
    """
    if not relevant_ids:
        return 1.0

    retrieved_k: Set[str] = set(retrieved_ids[:k])
    relevant_set: Set[str] = set(relevant_ids)

    hits = len(retrieved_k.intersection(relevant_set))
    return float(hits / len(relevant_set))

def calculate_precision_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int = 5) -> float:
    """Calculate Precision@K: fraction of top-k retrieved documents that are relevant.

    Args:
        retrieved_ids: Ordered list of document IDs returned by retriever.
        relevant_ids: List of ground-truth relevant document IDs.
        k: Cutoff rank.

    Returns:
        Precision score (0.0 to 1.0).
    """
    if k <= 0:
        return 0.0

    retrieved_k: Set[str] = set(retrieved_ids[:k])
    relevant_set: Set[str] = set(relevant_ids)

    hits = len(retrieved_k.intersection(relevant_set))
    return float(hits / k)

def calculate_mrr(all_retrieved_ids: List[List[str]], all_relevant_ids: List[List[str]]) -> float:
    """Calculate Mean Reciprocal Rank (MRR) across a collection of evaluation queries.

    MRR evaluates how high the FIRST relevant precedent appears in the ranking list.

    Args:
        all_retrieved_ids: List of retrieved ID lists (one per query).
        all_relevant_ids: List of ground-truth relevant ID lists (one per query).

    Returns:
        MRR score (0.0 to 1.0).
    """
    if not all_retrieved_ids or not all_relevant_ids:
        return 0.0

    reciprocal_ranks: List[float] = []

    for retrieved, relevant in zip(all_retrieved_ids, all_relevant_ids):
        relevant_set = set(relevant)
        rr = 0.0

        for rank, doc_id in enumerate(retrieved, start=1):
            if doc_id in relevant_set:
                rr = 1.0 / rank
                break

        reciprocal_ranks.append(rr)

    return float(sum(reciprocal_ranks) / len(reciprocal_ranks))
