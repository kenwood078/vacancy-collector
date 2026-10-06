"""Формирование текста для эмбеддинга — симметрично для вакансии и резюме.

Одинаковый порядок полей и одинаковые подписи для обеих сторон:
если поменять структуру только в одной функции — косинус между
вектором вакансии и вектором резюме потеряет смысл.

Идут только семантические поля. Жёсткие (city, work_format, experience,
salary, ready_to_relocate) живут в БД и работают как SQL-фильтры в matcher.
"""

EMPTY = "не указано"


def _join(items: list[str] | None) -> str:
    """Склеивает список строк через запятую; пустое → 'не указано'.

    Args:
        items: список строк или None.

    Returns:
        Строка с элементами через запятую или «не указано».
    """
    if not items:
        return EMPTY
    return ", ".join(items)


def _build_lines(name: str, row: dict) -> list[str]:
    """Общее тело embedding_text. Порядок полей фиксирован.

    Args:
        name: значение первой строки — name вакансии или role резюме.
        row: словарь с полями stack, tasks, certifications, domains,
             programming_languages, english_level.

    Returns:
        Список строк embedding_text.
    """
    return [
        f"Название: {name}",
        f"Стек: {_join(row.get('stack'))}",
        f"Задачи: {_join(row.get('tasks'))}",
        f"Сертификации: {_join(row.get('certifications'))}",
        f"Домены: {_join(row.get('domains'))}",
        f"Языки программирования: {_join(row.get('programming_languages'))}",
        f"Английский: {row.get('english_level') or 'unknown'}",
    ]


def build_vacancy_text(row: dict) -> str:
    """embedding_text для вакансии.

    Args:
        row: объединённая строка vacancy_analysis + vacancies
             (см. VacancyStorage.get_unembedded).

    Returns:
        Многострочный текст.
    """
    name = row.get("name") or EMPTY
    return "\n".join(_build_lines(name, row))


def build_resume_text(row: dict) -> str:
    """embedding_text для резюме.

    Args:
        row: строка из таблицы resumes или dict с теми же ключами.

    Returns:
        Многострочный текст.
    """
    role = row.get("role") or EMPTY
    return "\n".join(_build_lines(role, row))
