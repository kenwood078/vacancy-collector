"""Обёртка над Qwen3-Embedding-4B через LM Studio."""

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-qwen3-embedding-4b")
API_KEY = os.getenv("LLM_API_KEY", "not-needed")
TIMEOUT = 60

QUERY_INSTRUCTION = "Given a resume, retrieve relevant job vacancies"


class QwenEmbedder:
    """Клиент Qwen3-Embedding-4B."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Инициализирует клиент с указанными настройками.

        Args:
            base_url: URL сервера. None — из .env.
            model: имя модели. None — из .env.
            api_key: ключ. None — из .env.
        """
        base = (base_url or BASE_URL).rstrip("/")
        self.url = f"{base}/embeddings"
        self.model = model or MODEL
        self.api_key = api_key or API_KEY

    def _post(self, text: str) -> list[float]:
        """Отправляет текст на сервер эмбеддингов.

        Args:
            text: исходный текст.

        Returns:
            Вектор из первого элемента data ответа сервера.

        Raises:
            requests.RequestException: если запрос или HTTP-статус завершился ошибкой.
            ValueError: если ответ не является корректным JSON.
            KeyError: если в ответе нет ожидаемых полей.
            IndexError: если список data пуст.
        """
        r = requests.post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={"model": self.model, "input": text},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]

    def embed_document(self, text: str) -> list[float]:
        """Эмбеддинг документа (вакансии). Без префикса.

        Args:
            text: исходный текст.

        Returns:
            Вектор вакансии без инструкции в запросе.
        """
        return self._post(text)

    def embed_query(self, text: str) -> list[float]:
        """Эмбеддинг запроса (резюме). С инструкцией Qwen3.

        Args:
            text: исходный текст.

        Returns:
            Вектор резюме с инструкцией Qwen3 в запросе.
        """
        wrapped = f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"
        return self._post(wrapped)
