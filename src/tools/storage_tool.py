from crewai.tools import BaseTool
from src.storage import VacancyStorage
from typing import List, Dict

class SaveVacanciesTool(BaseTool):
    name: str = "SaveVacanciesTool"
    description: str = "Сохраняет список вакансий в базу данных и возвращает отчёт"

    def _run(self, vacancies: List[Dict]) -> str:
        storage = VacancyStorage()
        added, errors, total = storage.add_vacancies(vacancies)
        storage.close()
        return f"Добавлено {added}, ошибок {errors}, всего {total}"