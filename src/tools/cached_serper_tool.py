import json
import os

from crewai.tools import BaseTool
from crewai_tools import SerperDevTool
from dotenv import load_dotenv

from src.storage.cache import SearchCache

load_dotenv()
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
USE_CACHE = os.getenv("USE_CACHE").lower() == "true"


class CachedSerperTool(BaseTool):
    name: str = "CachedSerperTool"
    description: str = "Поиск в Google через Serper с кэшированием результатов. Используй для поиска вакансий."

    def _run(self, query: str) -> str:
        cache = SearchCache()
        key = cache.make_key(query)
        if USE_CACHE:
            cached = cache.get(key)
            if cached:
                return json.dumps(cached, ensure_ascii=False)

        serper = SerperDevTool(api_key=SERPER_API_KEY)
        data = serper._run(search_query=query)

        if USE_CACHE:
            cache.set(key, data)

        return json.dumps(data, ensure_ascii=False)
