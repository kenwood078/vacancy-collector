import logging

from src.collectors.serper import SerperClient
from src.collectors.scraper import scrape
from src.collectors.extractor import extract_vacancy
from src.storage import VacancyStorage

logger = logging.getLogger(__name__)


def collect(n_vacancies: int, query: str, llm) -> tuple[int, int, int]:
    """
    Собирает до n_vacancies новых вакансий по заданному поисковому запросу.

    Проходит по страницам выдачи Serper, для каждой новой ссылки скрапит
    страницу, извлекает поля через LLM и сохраняет в БД. Пропускает вакансии,
    которые уже есть в БД (по URL), и архивные (определяется в extract_vacancy).

    Args:
        n_vacancies: Максимальное количество новых вакансий для сбора.
        query: Поисковый запрос для Serper (например, site:hh.ru/vacancy ...).
        llm: Экземпляр CrewAI LLM, используемый для извлечения полей
            из текста одной вакансии. Каждый вызов изолирован.

    Returns:
        Кортеж (added, errors, attempts):
            - added: сколько новых вакансий успешно сохранено в БД;
            - errors: сколько ошибок при скрапинге или сохранении;
            - attempts: сколько ссылок было обработано всего.

    Raises:
        Не выбрасывает исключений — ошибки логируются и учитываются в errors.

    Example:
        >>> from crewai import LLM
        >>> from src.collectors.pipeline import collect
        >>> llm = LLM(model="openai/gpt-oss-20b", base_url="http://localhost:1234/v1",
        ...           api_key="not-needed")
        >>> added, errors, attempts = collect(
        ...     n_vacancies=5,
        ...     query='site:hh.ru/vacancy intitle:"Network Engineer" -архив',
        ...     llm=llm,
        ... )
        >>> print(added, errors, attempts)
        5 0 8
    """
    MAX_PAGES = 50
    added = errors = attempts = 0
    client = SerperClient()
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
                    logger.info(f"[{added}/{n_vacancies}] {data['name']} @ {data['company']}")
                else:
                    errors += 1

                if added >= n_vacancies:
                    stop = True
                    break
            if stop:
                break

    logger.info(f"Done: added={added}, errors={errors}, attempts={attempts}")
    return added, errors, attempts