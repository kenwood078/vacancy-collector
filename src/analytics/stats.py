import re
from collections import Counter

from .skills_keywords import SKILLS_KEYWORDS


def compute_statistics(vacancies: list[dict]) -> dict:
    """
    Принимает список вакансий (словарей) и возвращает статистику.
    """
    total = len(vacancies)
    by_city = _count_cities(vacancies)
    top_skills = _get_top_skills(vacancies, top_n=10)
    salary_stats = _compute_salary_stats(vacancies)
    companies = _get_top_companies(vacancies, top_n=5)

    return {
        "total": total,
        "by_city": by_city,
        "top_skills": top_skills,
        "salary_stats": salary_stats,
        "companies": companies,
    }


def _count_cities(vacancies: list[dict]) -> dict:
    city_count = Counter()
    for v in vacancies:
        city = v.get("city") or "не определено"
        city_count[city] += 1
    return dict(city_count)


def _get_top_skills(vacancies: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """Извлекает навыки из требований и возвращает топ-N."""
    skills_sorted = sorted(SKILLS_KEYWORDS, key=len, reverse=True)
    # Строим одно регулярное выражение
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(s) for s in skills_sorted) + r")(?!\w)",
        re.IGNORECASE,
    )
    skill_counter = Counter()
    for v in vacancies:
        text = v.get("requirements", "")
        if not text:
            continue
        # Находим все совпадения, уникальные для этой вакансии
        found = set(match.group(0).lower() for match in pattern.finditer(text))
        skill_counter.update(found)

    return skill_counter.most_common(top_n)


def _get_top_companies(vacancies: list[dict], top_n: int = 5) -> list[tuple[str, int]]:
    """Возвращает топ-N компаний по числу вакансий."""
    company_counter = Counter()
    for v in vacancies:
        company = v.get("company")
        if company:
            company_counter[company] += 1
    return company_counter.most_common(top_n)


def _parse_salary(salary_str: str) -> int | None:
    """
    Извлекает числовое значение зарплаты из строки.
    - Одно число -> возвращает его.
    - Два числа или больше -> возвращает среднее.
    - Если чисел нет -> None.
    """
    if not salary_str:
        return None

    # Убираем разделители тысяч внутри чисел (пробелы, запятые, точки)
    s = re.sub(r"(?<=\d)[\s,.](?=\d)", "", salary_str)

    # Находим все числа
    numbers = [int(n) for n in re.findall(r"\d+", s)]
    if not numbers:
        return None

    if len(numbers) == 1:
        return numbers[0]
    else:
        return sum(numbers) // len(numbers)


def _compute_salary_stats(vacancies: list[dict]) -> dict:
    """Возвращает словарь с min, max, avg и количеством без зарплаты."""
    salaries = []
    no_salary_count = 0
    for v in vacancies:
        salary_str = v.get("salary")
        parsed = _parse_salary(salary_str) if salary_str else None
        if parsed is not None:
            salaries.append(parsed)
        else:
            no_salary_count += 1
    if salaries:
        return {
            "min": min(salaries),
            "max": max(salaries),
            "avg": round(sum(salaries) / len(salaries), 2),
            "no_salary_count": no_salary_count,
        }
    else:
        return {
            "min": None,
            "max": None,
            "avg": None,
            "no_salary_count": no_salary_count,
        }
