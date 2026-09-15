import logging
import os

import requests
from dotenv import load_dotenv

from src.storage.cache import SearchCache

load_dotenv()
logger = logging.getLogger(__name__)

USE_CACHE = os.getenv("USE_CACHE", "true").lower() == "true"


class SerperClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self.api_key:
            raise ValueError("SERPER_API_KEY не задан")
        self.cache = SearchCache()

    def search(self, query: str, page: int = 1) -> list[dict]:
        key = self.cache.make_key(f"{query}|page={page}")

        if USE_CACHE:
            cached = self.cache.get(key)
            if cached:
                logger.info(f"Cache hit: {query[:50]} page={page}")
                return cached.get("organic", [])

        logger.info(f"Cache miss → Serper: {query[:50]} page={page}")
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            },
            json={"q": query, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if USE_CACHE:
            self.cache.set(key, data)

        return data.get("organic", [])

    def search_pages(self, query: str, pages: int = 3) -> list[dict]:
        results = []
        for i in range(pages):
            results.extend(self.search(query, page=i * 10))
        return results
