"""Векторный поиск вакансий по резюме."""

import logging

from src.storage import VacancyStorage

logger = logging.getLogger(__name__)


def _parse_vector(value: str | list[float]) -> list[float]:
    """Приводит вектор из БД к списку float.

    psycopg2 без регистрации pgvector-адаптера возвращает vector как строку
    вида "[-0.0004,0.0216,...]". Если значение уже список — возвращаем как есть.

    Args:
        value: строка или список.

    Returns:
        Список float.

    Raises:
        ValueError: если тип значения не поддерживается или числа некорректны.
    """
    if isinstance(value, list):
        return [float(x) for x in value]
    if isinstance(value, str):
        return [float(x) for x in value.strip("[]").split(",") if x]
    raise ValueError(f"Unexpected vector type: {type(value)}")


def match_resume(resume_id: int, top_n: int = 20) -> tuple[dict, list[dict]]:
    """Достаёт резюме из БД и находит top-N ближайших вакансий.

    Args:
        resume_id: ID резюме в таблице resumes.
        top_n: сколько вакансий вернуть.

    Returns:
        Кортеж (resume, matches), где resume — dict из БД,
        matches — список вакансий с полем score.

    Raises:
        ValueError: если резюме не найдено или у него нет эмбеддинга.
    """
    with VacancyStorage() as storage:
        resume = storage.get_resume(resume_id)
        if not resume:
            raise ValueError(f"Resume id={resume_id} not found")
        if not resume.get("embedding"):
            raise ValueError(f"Resume id={resume_id} has no embedding")

        embedding = _parse_vector(resume["embedding"])
        matches = storage.find_top_vacancies(embedding, resume=resume, top_n=top_n)

    logger.info("Matched resume %d: %d vacancies", resume_id, len(matches))
    return resume, matches
