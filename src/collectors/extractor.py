import json
import logging
import re

logger = logging.getLogger(__name__)

ARCHIVE_MARKERS = ["вакансия в архиве", "в архиве с"]


def extract_vacancy(text: str, url: str, llm) -> dict | None:
    if any(m in text.lower() for m in ARCHIVE_MARKERS):
        logger.info(f"Archive skip: {url}")
        return None

    prompt = f"""Извлеки данные из текста вакансии. Верни ТОЛЬКО валидный JSON без markdown:
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
    try:
        raw = llm.call(prompt)
        cleaned = re.sub(
            r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE
        ).strip()
        result = json.loads(cleaned)
        if not result or not result.get("name") or not result.get("company"):
            return None
        result["url"] = url
        logger.info(f"Extracted: {result['name']} @ {result['company']}")
        return result
    except Exception as e:
        logger.warning(f"Extract failed {url}: {e}")
        return None
