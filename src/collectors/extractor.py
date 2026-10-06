import json
import logging
from typing import TYPE_CHECKING

from src.analytics._extraction_utils import (
    MARKDOWN_FENCE as _MARKDOWN_FENCE,
)
from src.analytics._extraction_utils import (
    _clean_json_response,
)

if TYPE_CHECKING:
    from crewai import LLM

logger = logging.getLogger(__name__)

MARKDOWN_FENCE = _MARKDOWN_FENCE

ARCHIVE_MARKERS = ["вакансия в архиве", "в архиве с"]

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


def extract_vacancy(text: str, url: str, llm: "LLM") -> dict | None:
    """Извлекает поля вакансии из текста через один изолированный вызов LLM.

    Args:
        text: очищенный текст страницы вакансии.
        url: URL вакансии — добавляется в результат для сохранения в БД.
        llm: экземпляр CrewAI LLM с методом .call(prompt).

    Returns:
        Словарь с полями name, company, city, salary, requirements, url
        или None, если вакансия архивная, ответ невалиден, либо LLM упала.
    """
    if any(marker in text.lower() for marker in ARCHIVE_MARKERS):
        logger.info("Archive skip: %s", url)
        return None

    try:
        raw = llm.call(PROMPT_TEMPLATE.format(text=text))
        cleaned = _clean_json_response(raw)
        result = json.loads(cleaned)

        if not result or not result.get("name") or not result.get("company"):
            logger.warning("Missing required fields: %s", url)
            return None

        result["url"] = url
        logger.info("Extracted: %s @ %s", result["name"], result["company"])
        return result
    except Exception as e:  # noqa: BLE001 -- сохранить обработку всех ошибок операции
        logger.warning("Extract failed %s: %s", url, e)
        return None
