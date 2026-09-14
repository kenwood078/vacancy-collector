from crewai.tools import BaseTool

from src.storage import VacancyStorage


class CheckUrlTool(BaseTool):
    name: str = "CheckUrlTool"
    description: str = "Проверяет, есть ли вакансия с таким URL в базе данных. Возвращает 'exists' или 'new'."

    def _run(self, url: str) -> str:
        with VacancyStorage() as storage:
            return "exists" if storage.exists(url) else "new"
