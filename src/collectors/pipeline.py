import logging
from typing import TYPE_CHECKING

from src.collectors.extractor import extract_vacancy
from src.collectors.scraper import scrape
from src.collectors.serper import SerperClient
from src.storage import VacancyStorage

if TYPE_CHECKING:
    from crewai import LLM

logger = logging.getLogger(__name__)


def collect_hh(
    n_vacancies: int,
    query: str,
    area: list[int] | None = None,
    search_period: int | None = 30,
    search_field: str | list[str] | None = "name",
    experience: list[str] | None = None,
    work_format: list[str] | None = None,
    employment_form: str | None = None,
    excluded_text: str | None = None,
    salary: int | None = None,
    only_with_salary: bool = False,
    professional_role: int | None = None,
    max_pages: int = 50,
) -> tuple[int, int, int]:
    """Собирает до n_vacancies новых вакансий напрямую с hh.ru.

    Args:
        n_vacancies: сколько новых вакансий нужно.
        query: поисковый запрос (поддерживает NAME:, OR, NOT).
        area: коды регионов (1 — Москва, 2 — СПб). None → без ограничения.
        search_period: за сколько дней (1, 3, 7, 30).
        search_field: где искать — "name", "description", список или None.
        experience: список опыта — "between1And3", "between3And6" и т.д.
        work_format: список форматов — "REMOTE", "HYBRID", "ON_SITE".
        employment_form: "FULL", "PART", "CONTRACT", "PROJECT".
        excluded_text: минус-слова через пробел.
        salary: минимальная зарплата.
        only_with_salary: только вакансии с зарплатой.
        professional_role: ID роли (например, 112 — сетевой инженер).
        max_pages: максимум страниц (защита от бесконечного цикла).

    Returns:
        (added, errors, attempts).
    """
    # HH cookies нужны только для прямого сбора.
    from src.collectors.hh_client import HHClient

    client = HHClient()
    added = errors = attempts = 0
    page = 0
    stop = False

    with VacancyStorage() as storage:
        while added < n_vacancies and page < max_pages:
            results = client.search(
                query=query,
                area=area,
                page=page,
                search_period=search_period,
                search_field=search_field,
                experience=experience,
                work_format=work_format,
                employment_form=employment_form,
                excluded_text=excluded_text,
                salary=salary,
                only_with_salary=only_with_salary,
                professional_role=professional_role,
            )
            if not results:
                logger.info("Page %s empty, stopping", page)
                break

            logger.info("Page %s: %s results", page, len(results))

            for v in results:
                attempts += 1
                url = f"https://hh.ru/vacancy/{v['vacancyId']}"
                if storage.exists(url):
                    continue

                data = client.fetch_full(v)
                if not data:
                    logger.info("Skip (no detail): %s", v["vacancyId"])
                    continue

                # Проверка обязательных полей
                if not data.get("employer") or not data.get("name"):
                    logger.info("Skip (empty name/employer): %s", v["vacancyId"])
                    continue

                if storage.add_vacancy(data):
                    added += 1
                    logger.info("[%s/%s] %s", added, n_vacancies, data["name"])
                else:
                    errors += 1

                if added >= n_vacancies:
                    stop = True
                    break
            if stop:
                break
            page += 1

    logger.info(
        "Done: added=%s, errors=%s, attempts=%s, pages=%s",
        added,
        errors,
        attempts,
        page,
    )
    return added, errors, attempts


def collect_serper(
    n_vacancies: int,
    query: str,
    llm: "LLM",
    use_cache: bool | None = None,
) -> tuple[int, int, int]:
    """Собирает до n_vacancies новых вакансий: Serper → scrape → extract → БД.

    Пропускает уже существующие URL и архивные вакансии.

    Args:
        n_vacancies: сколько новых вакансий нужно.
        query: поисковый запрос для Serper.
        llm: экземпляр CrewAI LLM для извлечения полей.
        use_cache: использовать ли кэш поиска. None → из env USE_CACHE.

    Returns:
        (added, errors, attempts) — сохранено, ошибок, всего обработано.
    """
    MAX_PAGES = 50
    added = errors = attempts = 0
    client = SerperClient(use_cache=use_cache)
    stop = False

    with VacancyStorage() as storage:
        for page in range(1, MAX_PAGES + 1):
            results = client.search(query, page=page)
            if not results:
                break
            for item in results:
                url = item["link"]
                attempts += 1

                if storage.exists(url):
                    logger.info("Skip (exists): %s", url)
                    continue

                text = scrape(url)
                if not text:
                    errors += 1
                    continue

                data = extract_vacancy(text, url, llm)
                if not data:
                    continue

                # Маппинг company → employer
                if "company" in data:
                    data["employer"] = data.pop("company")

                if storage.add_vacancy(data):
                    added += 1
                    logger.info(
                        "[%s/%s] %s @ %s",
                        added,
                        n_vacancies,
                        data["name"],
                        data["employer"],
                    )
                else:
                    errors += 1

                if added >= n_vacancies:
                    stop = True
                    break
            if stop:
                break

    logger.info("Done: added=%s, errors=%s, attempts=%s", added, errors, attempts)
    return added, errors, attempts
