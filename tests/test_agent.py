import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from agent.llm_agent import LLMAgent


@pytest.mark.asyncio
async def test_is_relevant_cache():
    agent = LLMAgent()
    agent.use_openrouter = False
    agent.local_llm = MagicMock()
    agent.generate = AsyncMock(return_value="True")
    assert await agent.is_relevant("some text") is True
    assert agent.generate.call_count == 1
    assert await agent.is_relevant("some text") is True
    assert agent.generate.call_count == 1


@pytest.mark.asyncio
async def test_summarize():
    agent = LLMAgent()
    agent.generate = AsyncMock(return_value="Краткое саммари")
    result = await agent.summarize("Long text")
    assert result == "Краткое саммари"


@pytest.mark.asyncio
async def test_fallback_openrouter():
    with patch.dict(
        os.environ,
        {
            "LLM_PREFERENCE": "openrouter",
            "OPENROUTER_API_KEY": "fake",
            "LOCAL_MODEL_PATH": "/fake",
        },
    ):
        agent = LLMAgent()
        agent._call_openrouter = AsyncMock(side_effect=Exception("API error"))
        agent._call_local = AsyncMock(return_value="local answer")
        result = await agent.generate("test")
        assert result == "local answer"


@pytest.mark.asyncio
async def test_openrouter_only_no_fallback():
    with patch.dict(
        os.environ,
        {
            "LLM_PREFERENCE": "openrouter_only",
            "OPENROUTER_API_KEY": "fake",
        },
    ):
        agent = LLMAgent()
        agent._call_openrouter = AsyncMock(side_effect=Exception("API error"))
        with pytest.raises(RuntimeError):
            await agent.generate("test")
