from pathlib import Path
from typing import Any
from chromadb import PersistentClient


CHROMA_PATH = Path("./chroma_db")


class ChromaDBManager:
    """Класс для управления векторной базой данных ChromaDB."""
    
    def __init__(self, path: Path = CHROMA_PATH):
        self.client = PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name="telegram_news",
        )

    def save_posts(self, posts: list[dict[str, Any]]):
        """Сохраняет список постов в ChromaDB."""
        if not posts:
            return

        posts.sort(key=lambda x: x["date"])
        
        ids = [f"{post["channel"]}_{post['id']}" for post in posts]
        documents = [post["text"] for post in posts]
        metadatas = [{
            "id": post["id"],
            "channel": post["channel"],
            "date": post["date"],
            "link": post["link"]
        } for post in posts]

        count_before = self.collection.count()

        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

        count_after = self.collection.count()
        new_posts_count = count_after - count_before

        if new_posts_count == 0:
            return []
        
        return posts[-new_posts_count:]
