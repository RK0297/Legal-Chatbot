"""Indian Legal Guardrails and Bar Council of India Compliance Engine."""
import re
from typing import Dict, List, Optional, Tuple

BAR_COUNCIL_DISCLAIMER = (
    "\n\n---\n"
    "⚖️ **Statutory Legal Disclaimer (Advocates Act, 1961 & Bar Council of India Rules):**\n"
    "This AI-generated analysis is provided for general informational and educational purposes based on verified Indian legal data. "
    "It does not constitute formal legal counsel, statutory pleading, or an advocate-client relationship. "
    "For legal representation or actionable court proceedings, consult an advocate enrolled with your State Bar Council or "
    "contact the National Legal Services Authority (NALSA Helpline: 15100) for free legal assistance."
)

EMERGENCY_CATALOG = [
    {
        "category": "Women in Distress & Domestic Violence",
        "patterns": [
            r"\b(?:domestic violence|dowry|dahej|498-?a|sexual assault|rape|molest(?:ation)?|acid attack|marital rape|beating me|beaten by|cruelty by husband|in-laws tortur(?:e|ing)?|husband beating|wife beating)\b",
            r"(?:mar-peet|patni ko maara|dahej ke liye|shadi ke baad atyachar|aurat par humla|sasural wale maar)",
        ],
        "helplines": [
            {"service": "Women Helpline (All India)", "number": "1091 / 181"},
            {"service": "National Commission for Women (NCW)", "number": "7827170170"},
            {"service": "National Emergency Police Response", "number": "112"},
        ],
        "guidance": "If you or someone you know is in immediate physical danger, contact emergency services or the nearest police station immediately under Section 154 CrPC / Section 173 BNSS.",
    },
    {
        "category": "Cyber Crime & Financial Fraud",
        "patterns": [
            r"\b(?:cyber crime|cyber fraud|otp scam|otp fraud|bank account hacked|account hacked|sextortion|nude video blackmail|loan app harass(?:ment)?|crypto fraud|upi scam|phishing fraud|online fraud|fraudulent transaction)\b",
            r"(?:paisa duba diya|online thagi|khate se paise kat gaye|photo leak karne ki dhamki)",
        ],
        "helplines": [
            {"service": "National Cyber Crime Reporting Helpline", "number": "1930"},
            {"service": "National Cyber Crime Portal", "number": "https://cybercrime.gov.in"},
            {"service": "Financial Fraud Immediate Grievance", "number": "1930 (Golden Hour Reporting)"},
        ],
        "guidance": "Report financial transactions immediately within the 'Golden Hour' via 1930 to freeze fraudulent transfers across Indian banking channels.",
    },
    {
        "category": "Child Protection & POCSO",
        "patterns": [
            r"\b(?:child abuse|child labor|child sexual|pocso|minor assault|underage abuse|pedophil(?:ia|e)|kidnapp(?:ing)? of child|child trafficking)\b",
            r"(?:bachhe ke sath|bal shoshan|chhota bachha kidnap)",
        ],
        "helplines": [
            {"service": "CHILDLINE India (Ministry of WCD)", "number": "1098"},
            {"service": "National Commission for Protection of Child Rights (NCPCR)", "number": "011-23478200"},
            {"service": "National Emergency", "number": "112"},
        ],
        "guidance": "Mandatory reporting is required under Section 19 of the POCSO Act, 2012 for any suspected child abuse.",
    },
    {
        "category": "Illegal Police Detention & Custodial Distress",
        "patterns": [
            r"\b(?:illegal detention|police brutality|third degree|custodial torture|custodial violence|police refused fir|unlawful arrest|police harassing)\b",
            r"(?:police bina warrant pakad|thane me maar-peet|fir nahi likh rahe)",
        ],
        "helplines": [
            {"service": "NALSA Free Legal Aid Helpline", "number": "15100"},
            {"service": "National Human Rights Commission (NHRC)", "number": "14433"},
            {"service": "Senior Police Vigilance Helpline", "number": "112"},
        ],
        "guidance": "Under D.K. Basu v. State of West Bengal guidelines and Article 22(1) of the Constitution, the arrested person has the fundamental right to consult a legal practitioner of choice and inform family.",
    },
    {
        "category": "Mental Health & Crisis Intervention",
        "patterns": [
            r"\b(?:suicide|kill myself|end my life|want to die|commit suicide|self harm)\b",
            r"(?:atmahatya|jaan dena chahta|jeene ka mann nahi)",
        ],
        "helplines": [
            {"service": "Tele-MANAS (Govt of India 24x7)", "number": "14416 / 1800-891-4416"},
            {"service": "Kiran Mental Health Helpline (MSJE)", "number": "1800-599-0019"},
        ],
        "guidance": "Please reach out for professional crisis counseling. Support is confidential and freely accessible across all Indian states.",
    },
]

class LegalGuardrails:
    """Enforces Bar Council compliance, confidence gating, and emergency distress detection."""

    def __init__(self, relevance_threshold: float = 0.35):
        self.relevance_threshold = relevance_threshold

    def detect_emergency(self, query: str) -> Optional[Dict]:
        """Detect urgent distress keywords and return actionable emergency helplines."""
        query_lower = query.lower()
        for item in EMERGENCY_CATALOG:
            for pattern in item["patterns"]:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    return {
                        "category": item["category"],
                        "helplines": item["helplines"],
                        "guidance": item["guidance"],
                    }
        return None

    def format_emergency_banner(self, emergency_info: Dict) -> str:
        """Format high-visibility alert banner for emergency response."""
        banner = (
            f"🚨 **URGENT LEGAL & CRISIS ASSISTANCE ({emergency_info['category'].upper()})**\n\n"
            f"> {emergency_info['guidance']}\n>\n"
        )
        for h in emergency_info["helplines"]:
            banner += f"> - **{h['service']}**: `{h['number']}`\n"
        banner += "\n---\n\n"
        return banner

    def evaluate_confidence(
        self, candidates: List[Dict], threshold: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate whether retrieved legal precedents meet the confidence threshold.

        Returns:
            Tuple of (is_confident: bool, refusal_advisory: Optional[str])
        """
        active_threshold = threshold if threshold is not None else self.relevance_threshold

        if not candidates:
            refusal = (
                "⚠️ **Statutory Precedent Advisory:**\n\n"
                "I was unable to locate verified statutory provisions or judicial precedents in the Indian Law corpus "
                "closely matching the specific facts of your query.\n\n"
                "Under Bar Council of India guidelines, generating speculative or unverified legal counsel carries serious "
                "risk of prejudice. I recommend:\n"
                "1. Consulting an enrolled Advocate or legal counsel specializing in this domain.\n"
                "2. Visiting your nearest District Legal Services Authority (DLSA) or contacting NALSA (`15100`) for free legal guidance.\n"
                "3. Rephrasing your question with specific legal terms, acts, or factual circumstances."
            )
            return False, refusal

        # Check candidate scores
        top_score = 0.0
        c0 = candidates[0]
        if "rerank_score" in c0:
            top_score = c0["rerank_score"]
            # Cross-encoder logits: positive values indicate strong relevance
            is_confident = top_score > -2.0
        elif "similarity" in c0:
            top_score = c0["similarity"]
            is_confident = top_score >= active_threshold
        else:
            is_confident = True

        if not is_confident:
            refusal = (
                "⚠️ **Low Confidence Relevance Warning:**\n\n"
                f"The closest statutory precedent in the database scored below our confidence threshold ({top_score:.3f} vs {active_threshold:.3f}). "
                "While general legal principles may apply, specific statutory applicability must be verified by an advocate before initiating litigation."
            )
            return False, refusal

        return True, None

    def attach_disclaimer(self, response_text: str) -> str:
        """Ensure standardized Bar Council disclaimer is appended to the response."""
        if "Statutory Legal Disclaimer" in response_text or "Advocates Act, 1961" in response_text:
            return response_text
        return response_text.rstrip() + BAR_COUNCIL_DISCLAIMER
