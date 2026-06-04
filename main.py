import json
import re
from urllib.parse import unquote

from llama_cpp import Llama, LlamaGrammar
from llama_cpp_agent import (
    FunctionCallingAgent,
    MessagesFormatterType,
    LlamaCppFunctionTool,
)
from llama_cpp_agent.providers import LlamaCppPythonProvider

from newspaper import Article
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

llm_model = Llama(
    model_path="models/gemma-4-31B-it-UD-Q4_K_XL.gguf",
    n_ctx=20000,
    n_gpu_layers=50,
    flash_attn=True,
    n_threads=16,
    verbose=True,
)
provider = LlamaCppPythonProvider(llm_model)


class SearchNews(BaseModel):
    """Поиск статей (веб, блоги, новости) через DuckDuckGo."""

    query: str = Field(..., description="Поисковый запрос")
    max_results: int = Field(5, description="Максимум результатов")

    def run(self, **kwargs):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        params = {"q": self.query, "t": "h_"}
        try:
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params=params,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            results = []
            for result in soup.select(".result")[: self.max_results]:
                title_tag = result.select_one(".result__title a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                link = title_tag.get("href", "")
                if link.startswith("//"):
                    link = "https:" + link
                match = re.search(r"uddg=(https?%3A%2F%2F[^&]+)", link)
                if match:
                    link = unquote(match.group(1))
                results.append({"title": title, "url": link})

            return (
                results
                if results
                else [{"title": f"Ничего не найдено по '{self.query}'", "url": ""}]
            )
        except Exception as e:
            return [{"title": f"Ошибка поиска: {e}", "url": ""}]


class FetchArticle(BaseModel):
    """Загрузка и извлечение полного текста статьи."""

    url: str = Field(..., description="URL статьи")

    def run(self, **kwargs):
        try:
            article = Article(self.url)
            article.download()
            article.parse()
            return article.text[:8000]
        except Exception as e:
            return f"Ошибка: {e}"


search_tool = LlamaCppFunctionTool(SearchNews, name="search_news")
fetch_tool = LlamaCppFunctionTool(FetchArticle, name="fetch_article_text")

SYSTEM_PROMPT = (
    "Ты инструмент для поиска актуальных статей на технические темы "
    "(новости, блоги, научные публикации). "
    "Для начала используй search_news для поиска по заданным темам на русском и английском языках. "
    "Затем для каждого подходящего URL вызови fetch_article_text, чтобы получить контент. "
    "По каждой статье напиши краткий обзор (минимум 5 пунктов) и запомни его. "
    "Когда обработаешь достаточно уникальных новостей и научных статей(10 суммарно), просто ответь: 'СБОР ДАННЫХ ЗАВЕРШЁН'."
)

json_grammar_str = r"""
root   ::= array
array  ::= "[" ws (value (ws "," ws value)*)? ws "]"
value  ::= object
object ::= "{" ws "\"title\"" ws ":" ws string "," ws "\"url\"" ws ":" ws string "," ws "\"summary\"" ws ":" ws string ws "}"
string ::= "\"" char* "\""
char   ::= [^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
ws     ::= [ \t\n]*
"""
try:
    grammar = LlamaGrammar.from_string(json_grammar_str)
except Exception as e:
    print(f"Ошибка в GBNF: {e}")

agent = FunctionCallingAgent(
    provider,
    llama_cpp_function_tools=[search_tool, fetch_tool],
    allow_parallel_function_calling=True,
    messages_formatter_type=MessagesFormatterType.CHATML,
    system_prompt=SYSTEM_PROMPT,
    debug_output=False,
)

user_prompt = (
    "Тебе нужно найти, проанализировать и извлечь основную информацию из статей и новостей "
    "за последнюю неделю по следующим темам: биометрия, liveness, deepfake, цифровое ID, компьютерное зрение. "
    "В случае если по запросу не хватает новостей или статей(меньше 10), ищи по напрямую относящимся темам. "
    "Для научных статей предпочтительнее пользоваться arxiv."
)

raw_response = agent.generate_response(user_prompt)
print("Агент завершил сбор. Ответ:", raw_response)

messages = agent.llama_cpp_agent.chat_history.get_chat_messages()

final_user_msg = {
    "role": "user",
    "content": (
        "На основе всех запрошенных и обработанных выше статей "
        "сформируй итоговый JSON-массив. Каждый элемент должен содержать поля: "
        "title (название статьи), url (ссылка), summary (краткий обзор на русском). "
        "Выведи ТОЛЬКО JSON, без пояснений."
    ),
}
messages.append(final_user_msg)

json_result = llm_model.create_chat_completion(
    messages=messages,
    grammar=grammar,
    max_tokens=4096,
    temperature=0.0,
    top_p=0.95,
    repeat_penalty=1.1,
)

json_text = json_result["choices"][0]["message"]["content"]

try:
    summaries = json.loads(json_text)
except json.JSONDecodeError:
    print("Грамматика не помогла? Лог:", json_text)
    summaries = [
        {"title": "Ошибка", "url": "", "summary": "Не удалось распарсить JSON"}
    ]

md_lines = ["# Дайджест статей за последнюю неделю\n"]
for item in summaries:
    title = item.get("title", "Без названия")
    url = item.get("url", "")
    summary = item.get("summary", "")
    md_lines.append(f"## [{title}]({url})\n")
    md_lines.append(summary + "\n\n---\n")

with open("news_digest.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print("Дайджест сохранён в news_digest.md")
