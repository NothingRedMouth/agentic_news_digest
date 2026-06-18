from pathlib import Path
from typing import Any, List
from chromadb import PersistentClient

CHROMA_PATH = Path("./chroma_db")


class ChromaDBManager:
    def __init__(self, path: Path = CHROMA_PATH):
        self.client = PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name="telegram_news",
        )

    def save_posts(self, posts: List[dict[str, Any]]) -> List[dict[str, Any]]:
        if not posts:
            return []

        posts.sort(key=lambda x: x["date"])
        existing_ids = (
            set(self.collection.get()["ids"]) if self.collection.count() > 0 else set()
        )
        new_posts = []
        for post in posts:
            doc_id = f"{post['channel']}_{post['id']}"
            if doc_id in existing_ids:
                continue
            new_posts.append(post)

        if not new_posts:
            return []

        ids = [f"{p['channel']}_{p['id']}" for p in new_posts]
        documents = [p["text"] for p in new_posts]
        metadatas = [
            {
                "id": p["id"],
                "channel": p["channel"],
                "date": p["date"],
                "link": p["link"],
            }
            for p in new_posts
        ]

        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        return new_posts
