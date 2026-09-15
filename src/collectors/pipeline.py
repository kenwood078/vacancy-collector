import logging

from src.collectors.extractor import extract_vacancy
from src.collectors.scraper import scrape
from src.collectors.serper import SerperClient
from src.storage import VacancyStorage

logger = logging.getLogger(__name__)


def collect(
    n_vacancies: int,
    query: str,
    llm,
    use_cache: bool | None = None,
) -> tuple[int, int, int]:
    """
    Собирает до n_vacancies новых вакансий: Serper → scrape → extract → БД.

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
                    logger.info(f"Skip (exists): {url}")
                    continue

                text = scrape(url)
                if not text:
                    errors += 1
                    continue

                data = extract_vacancy(text, url, llm)
                if not data:
                    continue

                if storage.add_vacancy(data):
                    added += 1
                    logger.info(
                        f"[{added}/{n_vacancies}] {data['name']} @ {data['company']}"
                    )
                else:
                    errors += 1

                if added >= n_vacancies:
                    stop = True
                    break
            if stop:
                break

    logger.info(f"Done: added={added}, errors={errors}, attempts={attempts}")
    return added, errors, attempts
