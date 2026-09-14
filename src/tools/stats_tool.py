import json

from crewai.tools import BaseTool

from src.analytics.stats import _parse_salary, compute_statistics
from src.storage import VacancyStorage


class GetStatsTool(BaseTool):
    name: str = "GetStatsTool"
    description: str = (
        "Возвращает статистику по вакансиям из БД в виде JSON-строки: "
        "общее число, распределение по городам, топ навыков, зарплаты, топ компаний. "
        "Также включает 3 показательных примера вакансий (с минимальной, средней и максимальной зарплатой)."
    )

    def _run(self) -> str:
        with VacancyStorage() as storage:
            vacancies = storage.get_all()

        stats = compute_statistics(vacancies)
        examples = self._pick_examples(vacancies)

        return json.dumps(
            {"stats": stats, "examples": examples},
            ensure_ascii=False,
        )

    def _pick_examples(self, vacancies: list[dict]) -> list[dict]:
        """
        Выбирает 3 показательных примера:
        - с минимальной зарплатой,
        - с медианной зарплатой,
        - с максимальной зарплатой.
        Если зарплат нет — возвращает первые 3 вакансии.
        Возвращает только ключевые поля: name, company, city, salary.
        """
        if not vacancies:
            return []

        with_salary = [
            v
            for v in vacancies
            if v.get("salary") and _parse_salary(v["salary"]) is not None
        ]

        if not with_salary:
            picked = vacancies[:3]
        else:
            sorted_by_salary = sorted(
                with_salary, key=lambda v: _parse_salary(v["salary"])
            )
            low = sorted_by_salary[0]
            mid = sorted_by_salary[len(sorted_by_salary) // 2]
            high = sorted_by_salary[-1]
            picked = [low, mid, high]

        # Убираем дубликаты и оставляем только ключевые поля
        seen_urls = set()
        result = []
        for v in picked:
            url = v.get("url")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            result.append(
                {
                    "name": v.get("name"),
                    "company": v.get("company"),
                    "city": v.get("city"),
                    "salary": v.get("salary"),
                    "url": v.get("url"),
                }
            )
        return result
