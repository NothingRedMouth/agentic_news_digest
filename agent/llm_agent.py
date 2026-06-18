import asyncio
import json
import logging
from os import getenv
from typing import List, Optional
import aiohttp
from llama_cpp import Llama, LlamaGrammar
from .tools import RelevanceCache
import yaml
from pathlib import Path
from utils.google_sheets_logger import get_global_logger
from configs.grammars import (
    boolean_grammar,
    category_grammar,
    significance_grammar,
    duplicate_groups_grammar,
)

logger = logging.getLogger(__name__)
gs_logger = get_global_logger()


class LLMAgent:
    def __init__(self):
        self.openrouter_api_key = getenv("OPENROUTER_API_KEY")
        self.openrouter_model = getenv("OPENROUTER_MODEL")
        self.openrouter_timeout = int(getenv("OPENROUTER_TIMEOUT", 30))
        self.openrouter_max_tokens = int(getenv("OPENROUTER_MAX_TOKENS", 20000))
        self.local_model_path = getenv("LOCAL_MODEL_PATH")
        self.llm_preference = getenv("LLM_PREFERENCE", "openrouter").lower()
        if self.llm_preference not in ("openrouter", "openrouter_only", "local"):
            logger.warning(
                f"Некорректное LLM_PREFERENCE={self.llm_preference}, используем 'openrouter'"
            )
            self.llm_preference = "openrouter"

        self.local_llm = None
        if self.llm_preference == "local" or (
            self.llm_preference in ("openrouter", "openrouter_only")
            and self.local_model_path
        ):
            try:
                logger.info("Загружаем локальную модель...")
                self.local_llm = Llama(
                    model_path=self.local_model_path, n_ctx=15000, n_gpu_layers=50
                )
                logger.info("Локальная модель загружена")
            except Exception as e:
                logger.error(f"Не удалось загрузить локальную модель: {e}")
                if self.llm_preference == "local":
                    raise RuntimeError(
                        "LLM_PREFERENCE=local, но локальная модель не загружена"
                    )

        self.relevance_cache = RelevanceCache(ttl_seconds=3600)
        prompts_path = Path(__file__).parent.parent / "configs/prompts.yaml"
        with open(prompts_path, "r") as f:
            self.prompts = yaml.safe_load(f)
        self._last_tokens = 0

    async def _call_openrouter(self, prompt: str) -> str:
        timeout = aiohttp.ClientTimeout(total=self.openrouter_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.openrouter_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": self.openrouter_max_tokens,
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    usage = data.get("usage", {})
                    self._last_tokens = usage.get("total_tokens", 0)
                    logger.info(
                        f"OpenRouter токены: prompt={usage.get('prompt_tokens')}, "
                        f"completion={usage.get('completion_tokens')}, total={self._last_tokens}"
                    )
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await resp.text()
                    logger.error(f"OpenRouter error: {resp.status} - {error_text}")
                    raise Exception(f"OpenRouter API error: {resp.status}")

    async def _call_local(
        self, prompt: str, grammar: Optional[LlamaGrammar] = None
    ) -> str:
        if not self.local_llm:
            raise RuntimeError("Локальная модель не загружена")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.local_llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.openrouter_max_tokens,
                temperature=0.0,
                grammar=grammar,
            ),
        )
        self._last_tokens = 0
        return result["choices"][0]["message"]["content"]

    async def generate(
        self, prompt: str, grammar: Optional[LlamaGrammar] = None
    ) -> str:
        if self.llm_preference == "openrouter_only":
            if not self.openrouter_api_key:
                raise RuntimeError(
                    "LLM_PREFERENCE=openrouter_only, но OPENROUTER_API_KEY не задан"
                )
            return await self._call_openrouter(prompt)
        elif self.llm_preference == "local":
            if not self.local_llm:
                raise RuntimeError(
                    "LLM_PREFERENCE=local, но локальная модель не загружена"
                )
            return await self._call_local(prompt, grammar)
        else:
            if self.openrouter_api_key:
                try:
                    return await self._call_openrouter(prompt)
                except Exception as e:
                    logger.warning(
                        f"OpenRouter failed: {e}, falling back to local model"
                    )
                    if self.local_llm:
                        return await self._call_local(prompt, grammar)
                    else:
                        raise RuntimeError(
                            "OpenRouter недоступен, а локальная модель не загружена"
                        )
            else:
                logger.warning(
                    "OPENROUTER_API_KEY не задан, используем локальную модель"
                )
                if self.local_llm:
                    return await self._call_local(prompt, grammar)
                else:
                    raise RuntimeError("Ни OpenRouter, ни локальная модель недоступны")

    async def is_relevant(self, text: str) -> bool:
        cached = self.relevance_cache.get(text)
        if cached is not None:
            return cached
        prompt = self.prompts["relevance_prompt"].format(text=text[:2000])
        grammar = (
            LlamaGrammar.from_string(boolean_grammar()) if self.local_llm else None
        )
        answer = await self.generate(prompt, grammar=grammar)
        relevant = answer.strip().lower() == "true"
        self.relevance_cache.set(text, relevant)
        return relevant

    async def summarize(self, text: str) -> str:
        prompt = self.prompts["summary_prompt"].format(text=text[:3000])
        return await self.generate(prompt)

    async def create_digest(self, summaries: list) -> str:
        prompt = self.prompts["digest_prompt"].format(summaries="\n\n".join(summaries))
        return await self.generate(prompt)

    async def verify_summary(self, summary: str) -> str:
        prompt = self.prompts["verify_prompt"].format(summary=summary)
        return await self.generate(prompt)

    async def highlight_key_elements(self, text: str) -> str:
        prompt = self.prompts["highlight_prompt"].format(text=text)
        return await self.generate(prompt)

    async def determine_category(self, text: str) -> str:
        prompt = self.prompts["category_prompt"].format(text=text)
        grammar = (
            LlamaGrammar.from_string(category_grammar()) if self.local_llm else None
        )
        return (await self.generate(prompt, grammar=grammar)).strip()

    async def assess_significance(self, text: str) -> str:
        prompt = self.prompts["significance_prompt"].format(text=text)
        grammar = (
            LlamaGrammar.from_string(significance_grammar()) if self.local_llm else None
        )
        return (await self.generate(prompt, grammar=grammar)).strip()

    async def find_duplicates(self, summaries: List[str]) -> List[List[int]]:
        if not summaries:
            return []
        prompt = self.prompts["dedup_prompt"].format(summaries="\n".join(summaries))
        grammar = (
            LlamaGrammar.from_string(duplicate_groups_grammar())
            if self.local_llm
            else None
        )
        response = await self.generate(prompt, grammar=grammar)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return []
