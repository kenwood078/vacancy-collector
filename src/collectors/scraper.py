import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CHARS = 15_000


def scrape(url: str) -> str:
    """Возвращает очищенный текст страницы или пустую строку при ошибке."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Scrape failed {url}: {e}")
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    logger.info(f"Scraped {url}: {len(text)} chars")
    return text
