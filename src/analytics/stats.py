import re
from collections import Counter

from .skills_keywords import SKILLS_KEYWORDS

UNKNOWN_CITY = "не определено"


def compute_statistics(vacancies: list[dict]) -> dict:
    """
    Считает агрегированную статистику по списку вакансий.

    Args:
        vacancies: список словарей с полями city, company, salary, requirements.

    Returns:
        Словарь с ключами:
            - total: общее количество вакансий;
            - by_city: распределение по городам;
            - top_skills: топ-10 навыков;
            - salary_stats: min/max/avg и количество без зарплаты;
            - companies: топ-5 компаний.
    """
    return {
        "total": len(vacancies),
        "by_city": _count_cities(vacancies),
        "top_skills": get_top_skills(vacancies, top_n=10),
        "salary_stats": _compute_salary_stats(vacancies),
        "companies": _get_top_companies(vacancies, top_n=5),
    }


def _count_cities(vacancies: list[dict]) -> dict[str, int]:
    """Возвращает распределение вакансий по городам; пустой город → 'не определено'."""
    city_count = Counter()
    for v in vacancies:
        city = v.get("city") or UNKNOWN_CITY
        city_count[city] += 1
    return dict(city_count)


def get_top_skills(vacancies: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """
    Извлекает навыки из поля requirements и возвращает топ-N.

    Каждый навык учитывается не более одного раза на вакансию.
    """
    # Длинные навыки первыми, чтобы "VMware NSX" матчился раньше "VMware"
    skills_sorted = sorted(SKILLS_KEYWORDS, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(s) for s in skills_sorted) + r")(?!\w)",
        re.IGNORECASE,
    )

    skill_counter = Counter()
    for v in vacancies:
        text = v.get("requirements", "")
        if not text:
            continue
        found = {m.group(0).lower() for m in pattern.finditer(text)}
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


def parse_salary(salary_str: str) -> int | None:
    """
    Извлекает числовое значение зарплаты из строки.

    - Одно число → возвращает его.
    - Два и более чисел → возвращает среднее (целочисленное).
    - Если чисел нет → None.

    Учитывает разделители тысяч (пробелы, запятые, точки).
    """
    if not salary_str:
        return None

    s = re.sub(r"(?<=\d)[\s,.](?=\d)", "", salary_str)
    numbers = [int(n) for n in re.findall(r"\d+", s)]

    if not numbers:
        return None
    return sum(numbers) // len(numbers)


def _compute_salary_stats(vacancies: list[dict]) -> dict:
    """
    Возвращает статистику по зарплатам.

    Returns:
        Словарь с ключами min, max, avg (int или None) и no_salary_count.
    """
    salaries: list[int] = []
    no_salary_count = 0

    for v in vacancies:
        salary_str = v.get("salary")
        parsed = parse_salary(salary_str) if salary_str else None
        if parsed is not None:
            salaries.append(parsed)
        else:
            no_salary_count += 1

    if not salaries:
        return {
            "min": None,
            "max": None,
            "avg": None,
            "no_salary_count": no_salary_count,
        }

    return {
        "min": min(salaries),
        "max": max(salaries),
        "avg": round(sum(salaries) / len(salaries), 2),
        "no_salary_count": no_salary_count,
    }
