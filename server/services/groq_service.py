import os
import json
import logging
from typing import List, Dict, Optional, Generator
import requests

logger = logging.getLogger(__name__)

class GroqService:
    """Interacts with Groq Cloud API for ultra-low-latency Llama-70B inference."""

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self._groq_client = None

        # Attempt to initialize official groq SDK client if available
        try:
            from groq import Groq
            if self.api_key:
                self._groq_client = Groq(api_key=self.api_key)
                logger.info(f"Initialized official Groq SDK client for model '{self.model}'.")
            else:
                logger.warning("GROQ_API_KEY is not set. Groq client initialized in unconfigured state.")
        except ImportError:
            logger.info("groq package not installed. Falling back to direct HTTP REST calls.")

    def is_configured(self) -> bool:
        """Check if API key is provided."""
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    def check_health(self) -> bool:
        """Validate API key connectivity with Groq platform."""
        if not self.is_configured():
            return False

        try:
            # Lightweight probe
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Groq health probe failed: {e}")
            return False

    def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate conversational completion from Groq Llama-70B model.

        Args:
            messages: List of message dictionaries with 'role' ('system', 'user', 'assistant') and 'content'.
            temperature: Sampling temperature (default: 0.2).
            max_tokens: Maximum tokens to generate (default: 1500).

        Returns:
            Generated response string.
        """
        temp = temperature if temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.2"))
        tokens = max_tokens if max_tokens is not None else int(os.getenv("LLM_MAX_TOKENS", "1500"))

        if not self.is_configured():
            return (
                "⚠️ Groq API key is not configured. "
                "Please obtain a free API key from https://console.groq.com "
                "and set 'GROQ_API_KEY' in your server/.env file."
            )

        # 1. Use Groq SDK if available
        if self._groq_client:
            try:
                response = self._groq_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Groq SDK invocation error: {e}")
                # Fall through to HTTP attempt if SDK fails

        # 2. Direct HTTP REST fallback
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }

        try:
            response = requests.post(self.GROQ_API_URL, json=payload, headers=headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                error_detail = response.text
                logger.error(f"Groq API HTTP {response.status_code}: {error_detail}")
                return (
                    f"I encountered an error communicating with the Groq API ({response.status_code}). "
                    f"Please verify your model name '{self.model}' and API key."
                )
        except requests.exceptions.Timeout:
            logger.error("Groq request timed out after 60 seconds.")
            return "I apologize, but the response generation timed out. Please try your query again."
        except Exception as e:
            logger.error(f"Groq completion error: {e}")
            return f"An unexpected error occurred during Groq generation: {str(e)}"

    def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """Stream conversational completion tokens from Groq Llama-70B model.

        Args:
            messages: List of message dictionaries with 'role' and 'content'.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Yields:
            Token text deltas as received.
        """
        temp = temperature if temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.2"))
        tokens = max_tokens if max_tokens is not None else int(os.getenv("LLM_MAX_TOKENS", "1500"))

        if not self.is_configured():
            yield (
                "⚠️ Groq API key is not configured. "
                "Please obtain a free API key from https://console.groq.com "
                "and set 'GROQ_API_KEY' in your server/.env file."
            )
            return

        # 1. Use Groq SDK streaming if client initialized
        if self._groq_client:
            try:
                stream = self._groq_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else ""
                    if delta:
                        yield delta
                return
            except Exception as e:
                logger.error(f"Groq SDK streaming failed: {e}. Attempting HTTP streaming fallback.")

        # 2. HTTP SSE streaming fallback
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
            "stream": True,
        }

        try:
            with requests.post(self.GROQ_API_URL, json=payload, headers=headers, stream=True, timeout=60) as resp:
                if resp.status_code != 200:
                    yield f"Error connecting to Groq API ({resp.status_code}): {resp.text}"
                    return

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                    if line_str.startswith("data: "):
                        data_str = line_str[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(data_str)
                            delta = chunk_data["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            continue
        except Exception as e:
            logger.error(f"Groq HTTP stream error: {e}")
            yield f"\n[Streaming error: {str(e)}]"

