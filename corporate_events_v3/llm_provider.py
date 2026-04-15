"""
llm_provider.py - Abstracao de provider LLM.

Permite trocar de provider mudando uma linha em config.py, sem mexer
no resto do pipeline.

Hoje implementado: Gemini (via SDK oficial novo `google-genai`).
Proximos: OpenAI, Anthropic - mesma interface.
"""
from __future__ import annotations

import time

from . import config


class LLMProvider:
    """Interface base. Todo provider implementa triage() e analyze()."""

    def triage(self, prompt: str, max_output_tokens: int | None = None) -> str:
        raise NotImplementedError

    def analyze(
        self,
        prompt: str,
        max_output_tokens: int | None = None,
        json_mode: bool = True,
    ) -> str:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    """Provider para Google Gemini via SDK oficial novo `google-genai`."""

    def __init__(self, model_triage: str, model_deep: str, api_key: str):
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY nao encontrada nas variaveis de ambiente.\n"
                "Para configurar (PowerShell):\n"
                '  setx GEMINI_API_KEY "sua-chave-aqui"\n'
                "Reabra o terminal depois de rodar."
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise RuntimeError(
                "Pacote ausente. Instale com:\n  pip install google-genai"
            ) from e

        self._client = genai.Client(api_key=api_key)
        self._types = types
        self.model_triage_name = model_triage
        self.model_deep_name = model_deep

    def triage(self, prompt: str, max_output_tokens: int | None = None) -> str:
        max_tok = max_output_tokens or config.TRIAGE_MAX_OUTPUT_TOKENS
        cfg = self._types.GenerateContentConfig(
            max_output_tokens=max_tok,
            temperature=0.0,
            response_mime_type="application/json",
        )
        resp = self._client.models.generate_content(
            model=self.model_triage_name,
            contents=prompt,
            config=cfg,
        )
        return (getattr(resp, "text", "") or "").strip()

    def analyze(
        self,
        prompt: str,
        max_output_tokens: int | None = None,
        json_mode: bool = True,
    ) -> str:
        max_tok = max_output_tokens or config.DEEP_MAX_OUTPUT_TOKENS
        kwargs: dict = {
            "max_output_tokens": max_tok,
            "temperature": 0.2,
        }
        if json_mode:
            kwargs["response_mime_type"] = "application/json"

        # Thinking budget: limita quanto 'pensamento' consome do orcamento
        # de output (Gemini 2.5 pro usa thinking tokens).
        budget = getattr(config, "DEEP_THINKING_BUDGET", None)
        if budget is not None:
            try:
                kwargs["thinking_config"] = self._types.ThinkingConfig(
                    thinking_budget=int(budget)
                )
            except Exception:
                pass  # se o SDK nao suportar, ignora silenciosamente

        cfg = self._types.GenerateContentConfig(**kwargs)

        max_retries = getattr(config, "DEEP_MAX_RETRIES", 3)
        backoff = getattr(config, "DEEP_RETRY_BACKOFF_S", 4.0)
        last_err: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self.model_deep_name,
                    contents=prompt,
                    config=cfg,
                )
                text = (getattr(resp, "text", "") or "").strip()
                # Algumas vezes .text vem vazio com finish_reason=MAX_TOKENS
                # (thinking consumiu tudo). Tenta recuperar manualmente.
                if not text and getattr(resp, "candidates", None):
                    cand = resp.candidates[0]
                    content = getattr(cand, "content", None)
                    if content and getattr(content, "parts", None):
                        pieces = [
                            (getattr(p, "text", "") or "")
                            for p in content.parts
                        ]
                        text = "".join(pieces).strip()
                return text
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                retriable = (
                    "503" in msg or "unavailable" in msg or
                    "504" in msg or "429" in msg or
                    "deadline" in msg or "timeout" in msg
                )
                if attempt >= max_retries or not retriable:
                    raise
                wait = backoff * (2 ** attempt)
                time.sleep(wait)
        # nao deveria chegar aqui
        if last_err:
            raise last_err
        return ""


def get_provider() -> LLMProvider:
    """Factory: devolve o provider configurado em config.LLM_PROVIDER."""
    if config.LLM_PROVIDER == "gemini":
        return GeminiProvider(
            model_triage=config.LLM_TRIAGE[1],
            model_deep=config.LLM_DEEP[1],
            api_key=config.GEMINI_API_KEY,
        )
    raise NotImplementedError(
        f"Provider '{config.LLM_PROVIDER}' ainda nao implementado."
    )
