"""LLM-as-a-Judge Evaluation Engine using Groq Llama-70B."""
from typing import Dict, List, Optional
import json
import re
import logging

from server.services.groq_service import GroqService

logger = logging.getLogger(__name__)

def extract_json_dict(text: str) -> Dict:
    """Robustly extract and parse JSON dict even if reasoning or markdown accompanies it."""
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group(0))
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)

class LLMJudge:
    """Automated LLM-as-a-Judge to evaluate Faithfulness, Answer Relevance, and Context Precision."""

    def __init__(self, groq_service: GroqService):
        self.groq_service = groq_service

    def evaluate_faithfulness(self, question: str, context: str, answer: str) -> Dict:
        """Evaluate whether the generated legal answer is strictly grounded in the retrieved context (no hallucinations).

        Returns:
            Dict with 'score' (0.0 - 1.0), 'reasoning', and 'verdict'.
        """
        if not self.groq_service.is_configured():
            return {"score": 1.0, "reasoning": "Groq unconfigured; default pass", "verdict": "SKIPPED"}

        prompt = (
            "You are an impartial legal audit judge.\n"
            "Assess whether the statements in the ASSISTANT ANSWER are directly supported by the PROVIDED CONTEXT.\n"
            "Score on a scale of 0.0 to 1.0, where:\n"
            "- 1.0: Every claim is fully supported by the provided context.\n"
            "- 0.5: Part of the answer is supported, but introduces unsubstantiated claims.\n"
            "- 0.0: The answer contradicts the context or is entirely fabricated/hallucinated.\n\n"
            "CONTEXT:\n"
            f"{context}\n\n"
            "QUESTION:\n"
            f"{question}\n\n"
            "ASSISTANT ANSWER:\n"
            f"{answer}\n\n"
            "Respond ONLY with a JSON object in this format:\n"
            '{"score": <float between 0.0 and 1.0>, "reasoning": "<short explanation>"}'
        )

        messages = [
            {"role": "system", "content": "You are a legal AI evaluation judge. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = self.groq_service.generate_chat_completion(messages=messages, temperature=0.0, max_tokens=600)
            data = extract_json_dict(raw)
            score = float(data.get("score", 0.5))
            return {
                "score": max(0.0, min(1.0, score)),
                "reasoning": data.get("reasoning", "Faithfulness evaluated successfully."),
                "verdict": "PASS" if score >= 0.7 else "FAIL",
            }
        except Exception as e:
            logger.warning(f"Faithfulness evaluation error: {e}")
            return {"score": 0.5, "reasoning": f"Parsing failure: {e}", "verdict": "UNKNOWN"}

    def evaluate_answer_relevance(self, question: str, answer: str) -> Dict:
        """Evaluate how directly and completely the answer addresses the user's legal query.

        Returns:
            Dict with 'score' (0.0 - 1.0), 'reasoning', and 'verdict'.
        """
        if not self.groq_service.is_configured():
            return {"score": 1.0, "reasoning": "Groq unconfigured; default pass", "verdict": "SKIPPED"}

        prompt = (
            "You are an impartial legal audit judge.\n"
            "Evaluate whether the ASSISTANT ANSWER directly, completely, and accurately answers the USER QUESTION.\n"
            "Score on a scale of 0.0 to 1.0, where:\n"
            "- 1.0: Directly and comprehensively answers the legal inquiry.\n"
            "- 0.5: Partially answers the question or goes off on minor tangents.\n"
            "- 0.0: Completely irrelevant, avoids the question, or answers a different topic.\n\n"
            "QUESTION:\n"
            f"{question}\n\n"
            "ASSISTANT ANSWER:\n"
            f"{answer}\n\n"
            "Respond ONLY with a JSON object in this format:\n"
            '{"score": <float between 0.0 and 1.0>, "reasoning": "<short explanation>"}'
        )

        messages = [
            {"role": "system", "content": "You are a legal AI evaluation judge. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = self.groq_service.generate_chat_completion(messages=messages, temperature=0.0, max_tokens=600)
            data = extract_json_dict(raw)
            score = float(data.get("score", 0.5))
            return {
                "score": max(0.0, min(1.0, score)),
                "reasoning": data.get("reasoning", "Answer relevance evaluated successfully."),
                "verdict": "PASS" if score >= 0.7 else "FAIL",
            }
        except Exception as e:
            logger.warning(f"Answer relevance evaluation error: {e}")
            return {"score": 0.5, "reasoning": f"Parsing failure: {e}", "verdict": "UNKNOWN"}
