"""Векторный поиск вакансий по резюме."""

import logging
import time

from src.collectors.vacancy_status import (
    REQUEST_DELAY,
    check_vacancy_status,
    create_status_session,
    needs_status_check,
)
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
    """Находит top-N вакансий, проверяя актуальность кандидатов по сроку.

    Args:
        resume_id: ID резюме в таблице resumes.
        top_n: сколько вакансий вернуть.

    Returns:
        Кортеж (resume, matches), где resume — dict из БД,
        matches — список вакансий с полем score.

    Raises:
        ValueError: если top_n отрицательное, резюме не найдено или нет эмбеддинга.
        StatusCheckConfigError: если не заданы HH cookies.
    """
    if top_n < 0:
        raise ValueError("top_n must be nonnegative")
    with VacancyStorage() as storage:
        resume = storage.get_resume(resume_id)
        if not resume:
            raise ValueError(f"Resume id={resume_id} not found")
        if not resume.get("embedding"):
            raise ValueError(f"Resume id={resume_id} has no embedding")

        embedding = _parse_vector(resume["embedding"])
        matches: list[dict] = []
        seen: set[str] = set()
        requests_made = 0
        with create_status_session() as session:
            while len(matches) < top_n:
                candidates = storage.find_top_vacancies(
                    embedding, resume=resume, top_n=top_n
                )
                new_candidates = [v for v in candidates if v["url"] not in seen]
                if not new_candidates:
                    break
                for vacancy in new_candidates:
                    url = vacancy["url"]
                    seen.add(url)
                    if needs_status_check(vacancy):
                        if requests_made:
                            time.sleep(REQUEST_DELAY)
                        status = check_vacancy_status(url, session)
                        requests_made += 1
                        checked_at = storage.update_vacancy_status(url, status)
                        if checked_at is None:
                            continue
                        vacancy["status"] = status
                        vacancy["last_checked_at"] = checked_at
                    if vacancy.get("status") != "archived":
                        matches.append(vacancy)
                    if len(matches) >= top_n:
                        break

    logger.info("Matched resume %d: %d vacancies", resume_id, len(matches))
    return resume, matches
