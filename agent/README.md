# LLM-агент

- **LLMAgent** – обёртка над OpenRouter и локальной моделью (Gemma). Управляется переменной `LLM_PREFERENCE`. Поддерживает кэширование релевантности, асинхронные вызовы, автоматический fallback.
- **Инструменты** – `TelegramSearch`, `WebSearchExa`, `FetchArticle`, `RelevanceCache`.
- Промпты хранятся в `configs/prompts.yaml`.
