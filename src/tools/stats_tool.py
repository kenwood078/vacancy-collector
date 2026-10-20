import json
import logging
from calendar import monthrange
from datetime import datetime, timedelta, timezone

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

REPORT_PERIODS = {
    "30d": "Последний месяц (30 дней)",
    "3m": "Последние 3 месяца",
    "6m": "Последние 6 месяцев",
    "1y": "Последний год",
}


def _period_start(period: str, now: datetime) -> datetime:
    """Вычисляет начало периода, учитывая длину календарных месяцев."""
    if period not in REPORT_PERIODS:
        raise ValueError(f"Неизвестный период отчёта: {period}")
    if period == "30d":
        return now - timedelta(days=30)
    months = {"3m": 3, "6m": 6, "1y": 12}[period]
    year, month = divmod(now.year * 12 + now.month - 1 - months, 12)
    month += 1
    return now.replace(
        year=year, month=month, day=min(now.day, monthrange(year, month)[1])
    )


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
        "Выборка ограничена периодом по collected_at; period содержит label, "
        "start и end (UTC). Укажи выбранный период в начале отчёта. "
        "Плюс до 3 примеров вакансий "
        "(low/mid/high по зарплате) с полями name, employer, city, salary, "
        "top_skills, url."
    )
    specialization: str | None = Field(default=None, exclude=True)
    display_name: str | None = Field(default=None, exclude=True)
    professional_role: int | None = Field(default=None, exclude=True)
    skills_keywords: list[str] | None = Field(default=None, exclude=True)
    skill_groups: dict[str, list[str]] = Field(default_factory=dict, exclude=True)
    period: str = Field(default="1y", exclude=True)
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
        now = datetime.now(timezone.utc)
        start = _period_start(self.period, now)
        with VacancyStorage() as storage:
            vacancies = storage.get_for_report(self.professional_role, start, now)
        if not vacancies:
            logger.warning("No vacancies in DB")

        stats = compute_statistics(vacancies, self.skills_keywords)
        examples = self._pick_examples(vacancies)
        data = {
            "stats": stats,
            "examples": examples,
            "report_date": now.astimezone().strftime("%d.%m.%Y"),
            "period": {
                "label": REPORT_PERIODS[self.period],
                "start": start.isoformat(),
                "end": now.isoformat(),
            },
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
