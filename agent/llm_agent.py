import asyncio
import logging
from os import getenv
import aiohttp
from llama_cpp import Llama
from .tools import RelevanceCache
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


class LLMAgent:
    def __init__(self):
        self.openrouter_api_key = getenv("OPENROUTER_API_KEY")
        self.openrouter_model = getenv("OPENROUTER_MODEL")
        self.openrouter_timeout = int(getenv("OPENROUTER_TIMEOUT", 30))
        self.openrouter_max_tokens = int(getenv("OPENROUTER_MAX_TOKENS", 20000))
        self.local_model_path = getenv("LOCAL_MODEL_PATH")
        self.llm_preference = getenv("LLM_PREFERENCE").lower()

        if self.llm_preference not in ("openrouter", "openrouter_only", "local"):
            logger.warning(
                f"Некорректное LLM_PREFERENCE={self.llm_preference}, используем 'openrouter(default)'"
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
                    model_path=self.local_model_path, n_ctx=20000, n_gpu_layers=50
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
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.error(
                        f"OpenRouter error: {resp.status} - {await resp.text()}"
                    )
                    raise Exception(f"OpenRouter API error: {resp.status}")

    async def _call_local(self, prompt: str) -> str:
        if not self.local_llm:
            raise RuntimeError("Локальная модель не загружена")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.local_llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.openrouter_max_tokens,
                temperature=0.0,
            ),
        )
        return result["choices"][0]["message"]["content"]

    async def generate(self, prompt: str) -> str:
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
            return await self._call_local(prompt)

        else:
            if self.openrouter_api_key:
                try:
                    return await self._call_openrouter(prompt)
                except Exception as e:
                    logger.warning(
                        f"OpenRouter failed: {e}, falling back to local model"
                    )
                    if self.local_llm:
                        return await self._call_local(prompt)
                    else:
                        raise RuntimeError(
                            "OpenRouter недоступен, а локальная модель не загружена"
                        )
            else:
                logger.warning(
                    "OPENROUTER_API_KEY не задан, используем локальную модель"
                )
                if self.local_llm:
                    return await self._call_local(prompt)
                else:
                    raise RuntimeError("Ни OpenRouter, ни локальная модель недоступны")

    async def is_relevant(self, text: str) -> bool:
        cached = self.relevance_cache.get(text)
        if cached is not None:
            return cached
        prompt = self.prompts["relevance_prompt"].format(text=text[:2000])
        answer = await self.generate(prompt)
        relevant = answer.strip().lower() == "true"
        self.relevance_cache.set(text, relevant)
        return relevant

    async def summarize(self, text: str) -> str:
        prompt = self.prompts["summary_prompt"].format(text=text[:3000])
        return await self.generate(prompt)

    async def create_digest(self, summaries: list) -> str:
        prompt = self.prompts["digest_prompt"].format(summaries="\n\n".join(summaries))
        return await self.generate(prompt)
