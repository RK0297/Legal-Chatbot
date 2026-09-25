"""Self-Querying and Legal Query Reformulation Service with Indic Multi-Lingual Support."""
from typing import Dict, List, Optional
import json
import logging
import re
import os
from server.services.groq_service import GroqService

logger = logging.getLogger(__name__)

def detect_query_language(text: str) -> str:
    """Detect whether query is Hindi (Devanagari), Hinglish (Roman script Hindi), or English."""
    if re.search(r"[\u0900-\u097F]", text):
        return "Hindi"

    hinglish_markers = {
        "kya", "kaise", "karein", "karna", "hoga", "hogi", "nahi", "nahin",
        "meri", "mera", "mere", "apne", "hum", "padosi", "zameen", "kabza",
        "dahej", "shadi", "vivad", "police", "thane", "darj", "kanoon",
        "adhikar", "rok", "muavza", "dhamki", "dhokha", "paisa", "paise",
        "gaya", "gayi", "batao", "bataiye", "chahiye", "hai", "hain", "ke", "ki", "ko",
        "bhi", "par", "se", "me", "mein", "talaq", "vakil", "tareekh"
    }
    tokens = set(re.findall(r"\b[a-z]+\b", text.lower()))
    common = tokens.intersection(hinglish_markers)
    if len(common) >= 2 or (len(tokens) <= 4 and len(common) >= 1):
        return "Hinglish"

    return "English"

class SelfQueryService:
    """Reformulates colloquial and Indic queries into authoritative statutory search queries and extracts metadata filters."""

    def __init__(self, groq_service: GroqService):
        self.groq_service = groq_service

    def reformulate_and_extract(self, user_query: str) -> Dict:
        """Analyze user query, detect language, reformulate into formal English statutory terms, and extract filters.

        Args:
            user_query: Raw user input text (English, Hindi, or Hinglish).

        Returns:
            Dict containing:
                - 'original_query': str
                - 'reformulated_query': str
                - 'keywords': List[str]
                - 'category': Optional[str]
                - 'detected_language': str ("English" | "Hindi" | "Hinglish")
        """
        heuristic_lang = detect_query_language(user_query)

        fallback_result = {
            "original_query": user_query,
            "reformulated_query": user_query,
            "keywords": [user_query],
            "category": None,
            "detected_language": heuristic_lang,
        }

        if os.getenv("ENABLE_SELF_QUERY", "true").lower() != "true" or not self.groq_service.is_configured():
            return fallback_result

        system_prompt = (
            "You are an expert legal query analyzer for Indian jurisprudence (Constitution, IPC/BNS, CrPC/BNSS, CPC, NI Act, etc.).\n"
            "Your task is to analyze citizen queries written in English, Hindi (Devanagari), or Hinglish (Hindi in Roman script).\n"
            "If the query is in Hindi or Hinglish, TRANSLATE and REFORMULATE the core legal problem into formal Indian statutory search terms in ENGLISH, "
            "identifying the relevant Acts, Sections, and legal remedies for search indexing.\n\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            "{\n"
            '  "reformulated_query": "Formal statutory search query in ENGLISH citing applicable Indian Acts and sections",\n'
            '  "keywords": ["Statute title", "Section number", "Legal maxim", "Core remedy"],\n'
            '  "category": "Constitutional Law | Criminal Law | Civil Law | Family Law | Commercial Law | General",\n'
            '  "detected_language": "English | Hindi | Hinglish"\n'
            "}\n"
            "Do not output markdown code fences, thought tags, or explanations. Only raw JSON."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {user_query}"},
        ]

        try:
            raw_response = self.groq_service.generate_chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=600,
            )

            # Strip any markdown backticks if present
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_response.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

            data = json.loads(cleaned)
            reformulated = data.get("reformulated_query") or user_query
            keywords = data.get("keywords") or [user_query]
            category = data.get("category")
            detected_lang = data.get("detected_language") or heuristic_lang

            logger.info(f"Self-Query [{detected_lang}]: '{user_query}' -> '{reformulated}'")
            return {
                "original_query": user_query,
                "reformulated_query": reformulated,
                "keywords": keywords,
                "category": category,
                "detected_language": detected_lang,
            }
        except Exception as e:
            logger.warning(f"Self-Query reformulation failed: {e}. Utilizing fallback query.")
            return fallback_result

