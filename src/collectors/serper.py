import logging
import os

import requests
from dotenv import load_dotenv

from src.storage.cache import SearchCache

load_dotenv()
logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
TIMEOUT = 30


class SerperClient:
    """Клиент Serper API с кэшированием ответов на диск."""

    def __init__(
        self,
        api_key: str | None = None,
        use_cache: bool | None = None,
    ) -> None:
        """Инициализирует клиент с указанными настройками.

        Args:
            api_key: ключ Serper. Если None — берётся из env SERPER_API_KEY.
            use_cache: использовать ли кэш. Если None — берётся из env USE_CACHE.
        """
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self.api_key:
            raise ValueError("SERPER_API_KEY is not set")

        if use_cache is None:
            use_cache = os.getenv("USE_CACHE", "true").lower() == "true"
        self.use_cache = use_cache

        self.cache = SearchCache()

    def search(self, query: str, page: int = 1) -> list[dict]:
        """Ищет через Serper. Возвращает список organic-результатов.

        Args:
            query: поисковый запрос.
            page: номер страницы выдачи, начиная с 1.

        Returns:
            Список словарей {title, link, snippet, ...} или [] при пустом ответе.
        """
        key = self.cache.make_key(f"{query}|page={page}")

        if self.use_cache:
            cached = self.cache.get(key)
            if cached:
                logger.info("Cache hit: %s page=%s", query[:50], page)
                return cached.get("organic", [])

        logger.info("Cache miss → Serper: %s page=%s", query[:50], page)
        try:
            response = requests.post(
                SERPER_URL,
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "page": page},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.warning("Serper request failed (page=%s): %s", page, e)
            return []

        if self.use_cache:
            self.cache.set(key, data)

        return data.get("organic", [])

    def search_pages(self, query: str, pages: int = 3) -> list[dict]:
        """Возвращает organic-результаты с первых `pages` страниц.

        Args:
            query: поисковая строка.
            pages: число страниц выдачи.

        Returns:
            Результаты organic в порядке страниц.
        """
        results = []
        for page in range(1, pages + 1):
            results.extend(self.search(query, page=page))
        return results
