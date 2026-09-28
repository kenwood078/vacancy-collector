"""Проверка cookie-сессии hh.ru: можно ли получать вакансии через requests."""
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

HH_TOKEN = os.getenv("HH_TOKEN")
HH_XSRF = os.getenv("HH_XSRF")

if not HH_TOKEN or not HH_XSRF:
    raise ValueError("HH_TOKEN и HH_XSRF должны быть в .env")

session = requests.Session()
session.cookies.set("hhtoken", HH_TOKEN, domain=".hh.ru")
session.cookies.set("_xsrf", HH_XSRF, domain=".hh.ru")
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": "https://hh.ru/",
})

url = "https://hh.ru/search/vacancy"
params = {
    "text": '("Сетевой инженер" OR "Network Engineer" OR "Сетевой архитектор" OR "Сетевой администратор")',
    "area": [1, 2],
    "schedule": "remote",
    "order_by": "publication_time",
    "items_on_page": 100,
    "page": 0,
}

r = session.get(url, params=params, timeout=20)
print(f"\nStatus: {r.status_code}")
print(f"Content-Length: {len(r.text)}")

with open("hh_response.html", "w", encoding="utf-8") as f:
    f.write(r.text)
print("Сохранено в hh_response.html")