"""Проверка актуальности вакансий через cookie-сессию HH, без LLM."""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from src.collectors.extractor import ARCHIVE_MARKERS

logger = logging.getLogger(__name__)

ACTIVE_CHECK_INTERVAL = timedelta(days=7)
UNKNOWN_RETRY_INTERVAL = timedelta(days=1)
VALID_STATUSES = ("active", "archived", "unknown")
STATUS_TIMEOUT = 15
REQUEST_DELAY = 1.5


class StatusCheckConfigError(ValueError):
    """Отсутствуют обязательные cookies для проверки актуальности."""


def create_status_session() -> requests.Session:
    """Создаёт cookie-сессию HH только при запуске проверки.

    Returns:
        Сессия существующего HHClient.

    Raises:
        StatusCheckConfigError: если не заданы HH_TOKEN или HH_XSRF.
    """
    if not os.getenv("HH_TOKEN") or not os.getenv("HH_XSRF"):
        raise StatusCheckConfigError(
            "Для проверки актуальности нужны HH_TOKEN и HH_XSRF в .env."
        )

    from src.collectors.hh_client import HHClient

    return HHClient().session


def classify_vacancy_page(html: str) -> str:
    """Определяет статус по HTML успешного ответа страницы.

    Args:
        html: полный HTML, без ограничения длины.

    Returns:
        active, archived или unknown.
    """
    soup = BeautifulSoup(html, "html.parser")
    template = soup.find("template", id="HH-Lux-InitialState")
    state_text = template.get_text().strip() if template is not None else ""
    for tag in soup.find_all(["script", "style", "template"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True).lower()
    if any(marker in text for marker in ARCHIVE_MARKERS):
        return "archived"

    try:
        state = json.loads(state_text)
    except ValueError:
        return "unknown"
    if isinstance(state, dict):
        view = state.get("vacancyView")
        if isinstance(view, dict) and view:
            return "active"
    return "unknown"


def check_vacancy_status(url: str, session: requests.Session) -> str:
    """Открывает URL один раз и определяет статус вакансии.

    Args:
        url: сохранённый URL вакансии.
        session: cookie-сессия HH.

    Returns:
        active, archived или unknown при любой ошибке доступа.
    """
    try:
        response = session.get(url, timeout=STATUS_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Status check failed %s: %s", url, exc)
        return "unknown"
    if not 200 <= response.status_code < 300:
        return "unknown"
    status = classify_vacancy_page(response.text)
    logger.info("Status check %s: %s", url, status)
    return status


def needs_status_check(vacancy: dict, now: datetime | None = None) -> bool:
    """Проверяет срок актуальности; архивные записи не перепроверяются.

    Args:
        vacancy: запись с status и last_checked_at.
        now: время сравнения; по умолчанию текущее время UTC.

    Returns:
        True, если URL нужно проверить.
    """
    status = vacancy.get("status", "unknown")
    if status == "archived":
        return False
    checked_at = vacancy.get("last_checked_at")
    if checked_at is None:
        return True
    interval = ACTIVE_CHECK_INTERVAL if status == "active" else UNKNOWN_RETRY_INTERVAL
    return (now or datetime.now(timezone.utc)) - checked_at >= interval


def check_vacancy_statuses(n: int = 20) -> dict[str, int]:
    """Проверяет ограниченную порцию просроченных вакансий из БД.

    Args:
        n: максимальное число проверок, положительное целое.

    Returns:
        Количество сохранённых результатов по каждому статусу.

    Raises:
        ValueError: если n неположительное.
        StatusCheckConfigError: если нет обязательных cookies.
    """
    if n <= 0:
        raise ValueError("Количество проверок должно быть положительным.")

    from src.storage import VacancyStorage

    counts = dict.fromkeys(VALID_STATUSES, 0)
    with create_status_session() as session, VacancyStorage() as storage:
        vacancies = storage.get_due_for_status_check(limit=n)
        for index, vacancy in enumerate(vacancies):
            if index:
                time.sleep(REQUEST_DELAY)
            status = check_vacancy_status(vacancy["url"], session)
            if storage.update_vacancy_status(vacancy["url"], status) is not None:
                counts[status] += 1
    return counts
