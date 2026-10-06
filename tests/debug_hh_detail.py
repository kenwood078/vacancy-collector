"""Проверка detail-страницы hh.ru: description + keySkills."""

import json
import os
import sys

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HH_TOKEN = os.getenv("HH_TOKEN")
HH_XSRF = os.getenv("HH_XSRF")

session = requests.Session()
session.cookies.set("hhtoken", HH_TOKEN, domain=".hh.ru")
session.cookies.set("_xsrf", HH_XSRF, domain=".hh.ru")
session.headers.update(
    {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
)

vacancy_id = sys.argv[1] if len(sys.argv) > 1 else "131729634"
url = f"https://hh.ru/vacancy/{vacancy_id}"
print(f"Fetching: {url}")

r = session.get(url, timeout=20)
print(f"Status: {r.status_code}")

soup = BeautifulSoup(r.text, "html.parser")
tpl = soup.find("template", id="HH-Lux-InitialState")
data = json.loads(tpl.string)

vacancy = data["vacancyView"]

desc_html = vacancy.get("description", "")
desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)
skills = vacancy.get("keySkills", {}).get("keySkill", [])

requirements = desc_text
if skills:
    requirements += "\n\nКлючевые навыки: " + ", ".join(skills)

print(f"\nДлина описания: {len(desc_text)}")
print(f"Ключевых навыков: {len(skills)}")
print(f"Итоговая длина requirements: {len(requirements)}")
print("\n=== Первые 500 символов ===")
print(requirements[:500])
