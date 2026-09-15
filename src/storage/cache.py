import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

DEFAULT_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))


class SearchCache:
    """Файловый кэш JSON-ответов, ключ — md5 от строки запроса."""

    def __init__(
        self, cache_dir: str = "data/cache", ttl_hours: int | None = None
    ) -> None:
        """
        Создаёт папку кэша, если её нет.

        Args:
            cache_dir: путь к папке кэша.
            ttl_hours: время жизни записи в часах. None → вечный кэш.
                       По умолчанию берётся из env CACHE_TTL_HOURS (24).
                       Чтобы отключить TTL — передай 0 или отрицательное число.
        """
        self.cache_dir = cache_dir
        if ttl_hours is None:
            ttl_hours = DEFAULT_TTL_HOURS
        self.ttl_seconds = ttl_hours * 3600 if ttl_hours > 0 else None
        os.makedirs(self.cache_dir, exist_ok=True)

    @staticmethod
    def make_key(query: str) -> str:
        """Возвращает md5-хэш от строки запроса — используется как имя файла."""
        return hashlib.md5(query.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> str:
        """Полный путь к файлу кэша по ключу."""
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, key: str) -> dict | None:
        """
        Читает данные из кэша.

        Возвращает None, если файла нет, он повреждён или старше TTL.
        """
        path = self._path(key)
        if not os.path.exists(path):
            return None

        if self.ttl_seconds is not None:
            age = time.time() - os.path.getmtime(path)
            if age > self.ttl_seconds:
                logger.info(f"Cache expired ({key}, age={age / 3600:.1f}h)")
                return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cache read failed ({key}): {e}")
            return None

    def set(self, key: str, data: dict) -> None:
        """Сохраняет данные в кэш по ключу."""
        with open(self._path(key), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
