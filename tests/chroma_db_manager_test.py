import pytest
from db.chroma_db_manager import ChromaDBManager

@pytest.fixture
def temp_db_manager(tmp_path):
    """
    Фикстура создает ChromaDBManager в изолированной временной папке.
    После окончания теста папка автоматически удалится.
    """
    return ChromaDBManager(path=tmp_path / "test_chroma_db")


def test_chromadb_manager_deduplication(temp_db_manager):
    """
    Проверяем реальную дедупликацию внутри ChromaDBManager.
    Метод save_posts должен возвращать ТОЛЬКО те посты, которых ещё не было в базе.
    """
    db = temp_db_manager

    old_posts = [
        {
            "id": 553,
            "channel": "test_channel",
            "date": "2026-06-14 10:00:00",
            "text": "Старая новость 1",
            "link": "https://t.me/test_channel/553"
        },
        {
            "id": 554,
            "channel": "test_channel",
            "date": "2026-06-14 11:00:00",
            "text": "Старая новость 2",
            "link": "https://t.me/test_channel/554"
        }
    ]

    first_save_result = db.save_posts(old_posts)
    assert len(first_save_result) == 2
    assert db.collection.count() == 2

    mixed_posts = [
        old_posts[0],
        old_posts[1],
        {
            "id": 555,
            "channel": "test_channel",
            "date": "2026-06-14 12:00:00",
            "text": "Первая свежая новость",
            "link": "https://t.me/test_channel/555"
        },
        {
            "id": 556,
            "channel": "test_channel",
            "date": "2026-06-14 13:00:00",
            "text": "По приколу добавил ещё новый",
            "link": "https://t.me/test_channel/556"
        }
    ]

    returned_posts = db.save_posts(mixed_posts)

    assert db.collection.count() == 4

    assert len(returned_posts) == 2

    assert returned_posts[0]["id"] == 555
    assert returned_posts[0]["text"] == "Первая свежая новость"

    assert returned_posts[1]["id"] == 556
    assert returned_posts[1]["text"] == "По приколу добавил ещё новый"
