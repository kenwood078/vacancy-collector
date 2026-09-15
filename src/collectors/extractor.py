import json
import logging
import re

logger = logging.getLogger(__name__)

ARCHIVE_MARKERS = ["вакансия в архиве", "в архиве с"]
MARKDOWN_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)

PROMPT_TEMPLATE = """Извлеки данные из текста вакансии. Верни ТОЛЬКО валидный JSON без markdown:
{{
  "name": "название вакансии",
  "company": "компания",
  "city": "город или null",
  "salary": "зарплата строкой или null",
  "requirements": "краткое описание требований"
}}

Текст вакансии:
{text}
"""


def extract_vacancy(text: str, url: str, llm) -> dict | None:
    """
    Извлекает поля вакансии из текста через один изолированный вызов LLM.

    Args:
        text: очищенный текст страницы вакансии.
        url: URL вакансии — добавляется в результат для сохранения в БД.
        llm: экземпляр CrewAI LLM с методом .call(prompt).

    Returns:
        Словарь с полями name, company, city, salary, requirements, url
        или None, если вакансия архивная, ответ невалиден, либо LLM упала.
    """
    if any(marker in text.lower() for marker in ARCHIVE_MARKERS):
        logger.info(f"Archive skip: {url}")
        return None

    try:
        raw = llm.call(PROMPT_TEMPLATE.format(text=text))
        cleaned = MARKDOWN_FENCE.sub("", raw.strip()).strip()
        result = json.loads(cleaned)

        if not result or not result.get("name") or not result.get("company"):
            logger.warning(f"Missing required fields: {url}")
            return None

        result["url"] = url
        logger.info(f"Extracted: {result['name']} @ {result['company']}")
        return result
    except Exception as e:
        logger.warning(f"Extract failed {url}: {e}")
        return None
