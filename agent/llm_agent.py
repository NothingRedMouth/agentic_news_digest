import asyncio
import logging
from os import getenv
from typing import List, Dict
import aiohttp
import yaml
from pathlib import Path
from utils.google_sheets_logger import get_global_logger

logger = logging.getLogger(__name__)
gs_logger = get_global_logger()


class LLMAgent:
    def __init__(self):
        self.external_api_key = getenv("EXTERNAL_API_KEY")
        self.external_model = getenv("EXTERNAL_MODEL")
        self.external_timeout = int(getenv("EXTERNAL_TIMEOUT", 60))
        self.external_max_tokens = int(getenv("EXTERNAL_MAX_TOKENS", 30000))
        self.external_api_base_url = getenv(
            "EXTERNAL_API_BASE_URL", "https://openrouter.ai/api/v1"
        )

        self.local_server_url = getenv("LOCAL_LLM_SERVER_URL", "http://localhost:8080")
        self.local_server_timeout = int(getenv("LOCAL_LLM_TIMEOUT", 300))
        self.local_max_tokens = int(getenv("LOCAL_LLM_MAX_TOKENS", 30000))
        self.local_retries = int(getenv("LOCAL_LLM_RETRIES", 3))
        self.repeat_penalty = float(getenv("LOCAL_LLM_REPEAT_PENALTY", "1.1"))
        self.stop_tokens = (
            getenv("LOCAL_LLM_STOP", "").split(",") if getenv("LOCAL_LLM_STOP") else []
        )
        self.local_available = bool(self.local_server_url.strip())

        self.llm_preference = getenv("LLM_PREFERENCE", "external").lower()
        if self.llm_preference not in ("external", "external_only", "local"):
            logger.warning(
                f"Некорректное LLM_PREFERENCE={self.llm_preference}, используем 'external'"
            )
            self.llm_preference = "external"

        if self.llm_preference == "local" and not self.local_available:
            raise RuntimeError(
                "LLM_PREFERENCE=local, но LOCAL_LLM_SERVER_URL не задан или пуст"
            )

        prompts_path = Path(__file__).parent.parent / "configs/prompts.yaml"
        with open(prompts_path, "r") as f:
            self.prompts = yaml.safe_load(f)

    async def _call_external(self, messages: List[dict]) -> str:
        timeout = aiohttp.ClientTimeout(total=self.external_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {
                "Authorization": f"Bearer {self.external_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.external_model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": self.external_max_tokens,
            }
            url = f"{self.external_api_base_url}/chat/completions"
            async with session.post(
                url,
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    usage = data.get("usage", {})
                    logger.info(
                        f"External API токены: prompt={usage.get('prompt_tokens')}, "
                        f"completion={usage.get('completion_tokens')}, total={usage.get('total_tokens')}"
                    )
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await resp.text()
                    logger.error(f"External API error: {resp.status} - {error_text}")
                    raise Exception(f"External API error: {resp.status}")

    async def _call_local_with_retry(self, payload: dict) -> str:
        last_exception = None
        for attempt in range(1, self.local_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self.local_server_timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    url = f"{self.local_server_url}/v1/chat/completions"
                    async with session.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = data["choices"][0]["message"]["content"]
                            if not content or not content.strip():
                                logger.warning("Локальный сервер вернул пустой ответ")
                            return content.strip()
                        else:
                            error_text = await resp.text()
                            logger.error(
                                f"Локальный сервер ошибка (попытка {attempt}): {resp.status} - {error_text}"
                            )
                            raise Exception(f"Local server error: {resp.status}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                logger.warning(
                    f"Ошибка соединения с локальным сервером (попытка {attempt}): {e}"
                )
                if attempt < self.local_retries:
                    wait = 2**attempt
                    logger.info(f"Повтор через {wait} секунд...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"Все {self.local_retries} попыток к локальному серверу не удались"
                    )
                    raise RuntimeError(
                        f"Не удалось получить ответ от локального сервера: {last_exception}"
                    )
        raise RuntimeError("Неизвестная ошибка при вызове локального сервера")

    async def _call_local(self, messages: List[dict]) -> str:
        if not self.local_available:
            raise RuntimeError("Локальный сервер не настроен")

        payload = {
            "model": "default",
            "messages": messages,
            "max_tokens": self.local_max_tokens,
            "temperature": 0.0,
            "repeat_penalty": self.repeat_penalty,
            "stop": self.stop_tokens if self.stop_tokens else [],
        }
        return await self._call_local_with_retry(payload)

    async def generate(self, system_instruction: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ]

        if self.llm_preference == "external_only":
            if not self.external_api_key:
                raise RuntimeError(
                    "LLM_PREFERENCE=external_only, но EXTERNAL_API_KEY не задан"
                )
            return await self._call_external(messages)

        elif self.llm_preference == "local":
            if not self.local_available:
                raise RuntimeError(
                    "LLM_PREFERENCE=local, но локальный сервер недоступен"
                )
            return await self._call_local(messages)

        else:
            if self.external_api_key:
                try:
                    return await self._call_external(messages)
                except Exception as e:
                    logger.warning(
                        f"External API failed: {e}, falling back to local server"
                    )
                    if self.local_available:
                        return await self._call_local(messages)
                    else:
                        raise RuntimeError(
                            "External API недоступен, а локальный сервер не настроен"
                        )
            else:
                logger.warning("EXTERNAL_API_KEY не задан, используем локальный сервер")
                if self.local_available:
                    return await self._call_local(messages)
                else:
                    raise RuntimeError(
                        "Ни External API, ни локальный сервер недоступны"
                    )

    async def generate_digest_from_raw(self, contents: List[Dict]) -> str:
        MAX_SOURCES = 30
        MAX_TEXT_LEN = 1500
        selected = contents[:MAX_SOURCES]
        formatted = []
        for idx, item in enumerate(selected, 1):
            title = item.get("title", "Без заголовка")[:100]
            text = item.get("text", "")[:MAX_TEXT_LEN]
            date = item.get("date", "")
            url = item.get("url", "#")
            image = item.get("image", "")
            image_line = f"{image}" if image else "Картинки нет :("
            formatted.append(
                f"Источник {idx}:\n"
                f"Заголовок: {title}\n"
                f"Дата: {date}\n"
                f"Ссылка: {url}\n"
                f"{image_line}\n"
                f"Текст:\n{text}\n"
                "---"
            )
        combined = "\n\n".join(formatted)
        system = self.prompts["system_prompt"]
        user = self.prompts["digest_from_raw_prompt"].format(sources=combined)
        return await self.generate(system, user)
