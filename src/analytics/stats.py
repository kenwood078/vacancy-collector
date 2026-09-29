import re
from collections import Counter

from .skills_keywords import SKILLS_KEYWORDS

UNKNOWN_CITY = "не определено"


def compute_statistics(vacancies: list[dict]) -> dict:
    """
    Считает агрегированную статистику по списку вакансий.

    Args:
        vacancies: список словарей из БД.

    Returns:
        Словарь с ключами:
            - total: общее количество вакансий;
            - by_city: распределение по городам;
            - by_experience: распределение по опыту;
            - by_work_format: распределение по формату работы;
            - by_employment: распределение по типу занятости;
            - top_skills: топ-10 навыков из поля requirements (regex);
            - top_key_skills: топ-10 навыков из key_skills (готовые теги hh.ru);
            - salary_stats: min/max/avg и количество без зарплаты;
            - employers: топ-10 работодателей.
    """
    return {
        "total": len(vacancies),
        "by_city": _count_cities(vacancies),
        "by_experience": _count_by_field(vacancies, "experience"),
        "by_work_format": _count_work_formats(vacancies),
        "by_employment": _count_by_field(vacancies, "employment_form"),
        "top_skills": get_top_skills(vacancies, top_n=10),
        "top_key_skills": get_top_key_skills(vacancies, top_n=10),
        "salary_stats": _compute_salary_stats(vacancies),
        "employers": _get_top_employers(vacancies, top_n=10),
    }


def _count_cities(vacancies: list[dict]) -> dict[str, int]:
    """Возвращает распределение вакансий по городам; пустой город → 'не определено'."""
    city_count = Counter()
    for v in vacancies:
        city = v.get("city") or UNKNOWN_CITY
        city_count[city] += 1
    return dict(city_count)


def _count_by_field(
    vacancies: list[dict], field: str, unknown: str = "не указано"
) -> dict[str, int]:
    """
    Считает распределение вакансий по значению поля.

    None и пустые строки попадают в бакет `unknown`.
    """
    counter = Counter()
    for v in vacancies:
        value = v.get(field) or unknown
        counter[value] += 1
    return dict(counter)


def _count_work_formats(vacancies: list[dict]) -> dict[str, int]:
    """
    Считает распределение по форматам работы.

    work_format хранится строкой через запятую ("REMOTE,HYBRID"),
    поэтому одна вакансия может попасть в несколько бакетов.
    """
    counter = Counter()
    for v in vacancies:
        wf = v.get("work_format")
        if not wf:
            counter["не указано"] += 1
            continue
        for fmt in wf.split(","):
            fmt = fmt.strip()
            if fmt:
                counter[fmt] += 1
    return dict(counter)


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


def get_top_key_skills(vacancies: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """
    Извлекает ключевые навыки из поля key_skills и возвращает топ-N.

    Поле key_skills в БД хранится как строка с навыками через запятую.
    Регистр приводится к нижнему, пробелы обрезаются.

    Returns:
        Список кортежей [(навык, количество), ...] длиной до top_n.
    """
    counter = Counter()
    for v in vacancies:
        text = v.get("key_skills") or ""
        for skill in text.split(","):
            s = skill.strip().lower()
            if s:
                counter[s] += 1
    return counter.most_common(top_n)


def _get_top_employers(vacancies: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """Возвращает топ-N работодателей по числу вакансий."""
    employer_counter = Counter()
    for v in vacancies:
        employer = v.get("employer")
        if employer:
            employer_counter[employer] += 1
    return employer_counter.most_common(top_n)


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
