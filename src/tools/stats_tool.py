import json
import logging
from datetime import datetime

from crewai.tools import BaseTool

from src.analytics.stats import compute_statistics, get_top_skills, parse_salary
from src.storage import VacancyStorage

logger = logging.getLogger(__name__)


class GetStatsTool(BaseTool):
    """Инструмент для writer-агента: возвращает агрегаты по вакансиям из БД."""

    name: str = "GetStatsTool"
    description: str = (
        "Возвращает JSON со статистикой по вакансиям из БД: total, by_city, "
        "by_experience, by_work_format, by_employment, top_skills, "
        "top_key_skills, salary_stats, employers. Плюс 3 примера вакансий "
        "(low/mid/high по зарплате) с полями name, employer, city, salary, "
        "top_skills, url."
    )

    def _run(self) -> str:
        """Читает вакансии из БД и возвращает статистику + примеры как JSON.

        Returns:
            JSON с ключами stats, examples и report_date.
        """
        with VacancyStorage() as storage:
            vacancies = storage.get_all()
        if not vacancies:
            logger.warning("No vacancies in DB")

        stats = compute_statistics(vacancies)
        examples = self._pick_examples(vacancies)

        return json.dumps(
            {
                "stats": stats,
                "examples": examples,
                "report_date": datetime.now().astimezone().strftime("%d.%m.%Y"),
            },
            ensure_ascii=False,
        )

    def _pick_examples(self, vacancies: list[dict]) -> list[dict]:
        """Выбирает 3 показательных примера: с минимальной, медианной и
        максимальной зарплатой. Если зарплат нет — первые 3 вакансии.

        В каждом примере: name, employer, city, salary, top_skills (до 5), url.

        Args:
            vacancies: список словарей вакансий.

        Returns:
            До трёх примеров с уникальными URL, включая навыки каждой вакансии.
        """
        if not vacancies:
            return []

        with_salary: list[tuple[dict, int]] = []
        for vacancy in vacancies:
            if vacancy.get("salary"):
                salary = parse_salary(vacancy["salary"])
                if salary is not None:
                    with_salary.append((vacancy, salary))

        if not with_salary:
            picked = vacancies[:3]
        else:
            sorted_by_salary = sorted(with_salary, key=lambda item: item[1])
            picked = [
                sorted_by_salary[0][0],
                sorted_by_salary[len(sorted_by_salary) // 2][0],
                sorted_by_salary[-1][0],
            ]

        seen_urls: set[str] = set()
        result = []
        for v in picked:
            url = v.get("url")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            skills = get_top_skills([v], top_n=5)
            result.append(
                {
                    "name": v.get("name"),
                    "employer": v.get("employer"),
                    "city": v.get("city"),
                    "salary": v.get("salary"),
                    "top_skills": [s for s, _ in skills],
                    "url": url,
                }
            )
        return result
