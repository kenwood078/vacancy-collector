import json
import logging
from datetime import datetime

from crewai.tools import BaseTool
from pydantic import Field, PrivateAttr

from src.analytics.stats import (
    compute_skill_groups,
    compute_statistics,
    get_top_skills_for_keywords,
    parse_salary,
)
from src.storage import VacancyStorage

logger = logging.getLogger(__name__)


def _select_examples(vacancies: list[dict]) -> list[dict]:
    """Выбирает вакансии по минимальной, медианной и максимальной зарплате.

    Args:
        vacancies: вакансии в порядке выборки хранилища.

    Returns:
        Три позиции из стабильной сортировки по зарплате, возможно с повторами.
        Если зарплаты не распознаны — первые три вакансии.
    """
    with_salary: list[tuple[dict, int]] = []
    for vacancy in vacancies:
        if vacancy.get("salary"):
            salary = parse_salary(vacancy["salary"])
            if salary is not None:
                with_salary.append((vacancy, salary))

    if not with_salary:
        return vacancies[:3]

    sorted_by_salary = sorted(with_salary, key=lambda item: item[1])
    return [
        sorted_by_salary[0][0],
        sorted_by_salary[len(sorted_by_salary) // 2][0],
        sorted_by_salary[-1][0],
    ]


class GetStatsTool(BaseTool):
    """Инструмент для writer-агента: возвращает агрегаты по вакансиям из БД."""

    name: str = "GetStatsTool"
    description: str = (
        "Возвращает JSON со статистикой по вакансиям из БД: total, by_city, "
        "by_experience, by_work_format, by_employment, top_skills, "
        "top_key_skills, salary_stats, employers. Для профильного отчёта также "
        "specialization, display_name, professional_role и skill_groups "
        "(count и percent). professional_role — код роли HH, не количество. "
        "Количество вакансий — stats.total. Группы пересекаются; их частоты "
        "нельзя суммировать для получения общего числа вакансий. "
        "Плюс до 3 примеров вакансий "
        "(low/mid/high по зарплате) с полями name, employer, city, salary, "
        "top_skills, url."
    )
    specialization: str | None = Field(default=None, exclude=True)
    display_name: str | None = Field(default=None, exclude=True)
    professional_role: int | None = Field(default=None, exclude=True)
    skills_keywords: list[str] | None = Field(default=None, exclude=True)
    skill_groups: dict[str, list[str]] = Field(default_factory=dict, exclude=True)
    _payload: str | None = PrivateAttr(default=None)

    def prepare(self) -> bool:
        """Закрепляет выборку и рассчитывает данные до запуска writer.

        Returns:
            True, если выборка не пуста. Последующие вызовы инструмента
            возвращают подготовленный JSON без повторного чтения БД.

        Raises:
            ValueError: не заданы код роли HH или словарь навыков профиля.
        """
        if self.professional_role is None:
            raise ValueError("Для профильного отчёта требуется professional_role")
        if self.skills_keywords is None:
            raise ValueError("Для профильного отчёта требуется skills_keywords")
        with VacancyStorage() as storage:
            vacancies = storage.get_by_professional_role(self.professional_role)
        if not vacancies:
            logger.warning("No vacancies in DB")

        stats = compute_statistics(vacancies, self.skills_keywords)
        examples = self._pick_examples(vacancies)
        data = {
            "stats": stats,
            "examples": examples,
            "report_date": datetime.now().astimezone().strftime("%d.%m.%Y"),
        }
        if self.specialization is not None:
            data.update(
                specialization=self.specialization,
                display_name=self.display_name,
                professional_role=self.professional_role,
                skill_groups=compute_skill_groups(vacancies, self.skill_groups),
            )
        self._payload = json.dumps(data, ensure_ascii=False)
        return bool(vacancies)

    def _run(self) -> str:
        """Возвращает закреплённую статистику выбранного профиля.

        Returns:
            JSON с агрегатами, примерами и датой; для профильного отчёта
            также специализация, код роли и группы навыков.
        """
        if self._payload is None:
            self.prepare()
        assert self._payload is not None
        return self._payload

    def _pick_examples(self, vacancies: list[dict]) -> list[dict]:
        """Выбирает 3 показательных примера: с минимальной, медианной и
        максимальной зарплатой. Если зарплат нет — первые 3 вакансии.

        В каждом примере: name, employer, city, salary, top_skills (до 5), url.

        Args:
            vacancies: список словарей вакансий.

        Returns:
            До трёх примеров с уникальными URL, включая навыки каждой вакансии.

        Raises:
            ValueError: не задан словарь навыков профиля.
        """
        if not vacancies:
            return []
        if self.skills_keywords is None:
            raise ValueError("Для профильного отчёта требуется skills_keywords")

        seen_urls: set[str] = set()
        result = []
        for v in _select_examples(vacancies):
            url = v.get("url")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            skills = get_top_skills_for_keywords(
                [v],
                self.skills_keywords,
                top_n=5,
            )
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
