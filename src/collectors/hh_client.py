import json
import logging
import os
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

HH_BASE = "https://hh.ru"
HH_SEARCH = f"{HH_BASE}/search/vacancy"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
TIMEOUT = 20

HH_TOKEN = os.getenv("HH_TOKEN")
HH_XSRF = os.getenv("HH_XSRF")

if not HH_TOKEN or not HH_XSRF:
    raise ValueError("HH_TOKEN and HH_XSRF are required")

CURRENCY_SYMBOLS = {
    "RUR": "₽",
    "USD": "$",
    "EUR": "€",
    "KZT": "₸",
}


_NOT_FOUND = object()


def _find_key(obj, key: str):
    """Рекурсивно ищет ключ в dict/list."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]  # вернёт даже None
        for v in obj.values():
            result = _find_key(v, key)
            if result is not _NOT_FOUND:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_key(item, key)
            if result is not _NOT_FOUND:
                return result
    return _NOT_FOUND


class HHClient:
    def __init__(self):
        """Создаёт requests.Session с cookies из .env."""
        self.session = requests.Session()
        self.session.cookies.set("hhtoken", HH_TOKEN, domain=".hh.ru")
        self.session.cookies.set("_xsrf", HH_XSRF, domain=".hh.ru")
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"{HH_BASE}/",
            }
        )

    @staticmethod
    def _extract_state(html: str) -> dict:
        """Парсит template#HH-Lux-InitialState → dict."""
        soup = BeautifulSoup(html, "html.parser")
        tpl = soup.find("template", id="HH-Lux-InitialState")
        if tpl is None:
            raise ValueError("HH-Lux-InitialState template not found")
        return json.loads(tpl.get_text().strip())

    def search(
        self,
        query: str,
        area: list[int] | None = None,
        page: int = 0,
        items_on_page: int = 100,
        search_period: int | None = None,
        search_field: str | list[str] | None = None,
        experience: list[str] | None = None,
        employment_form: str | None = None,
        work_format: list[str] | None = None,
        excluded_text: str | None = None,
        salary: int | None = None,
        only_with_salary: bool = False,
        professional_role: int | None = None,
        order_by: str = "publication_time",
    ) -> list[dict]:
        """
        Возвращает список вакансий (сырые dict из hh.ru).

        Args:
            query: поисковая строка (поддерживает операторы NAME:, OR, NOT, "...").
            area: коды регионов (1 — Москва, 2 — СПб).
            page: номер страницы, начиная с 0.
            items_on_page: число результатов на странице (макс. 100).
            search_period: за сколько последних дней искать (1, 3, 7, 30).
            search_field: где искать — "name", "description", "company_name",
                          "full_text" или список из них.
            experience: список значений опыта:
                        "noExperience", "between1And3", "between3And6", "moreThan6".
            employment_form: тип занятости: "FULL", "PART", "CONTRACT", "PROJECT".
            work_format: список форматов работы:
                         "ON_SITE", "REMOTE", "HYBRID", "FIELD_WORK".
            excluded_text: слова, которые должны быть исключены из выдачи.
            salary: минимальная зарплата (руб.).
            only_with_salary: искать только вакансии с указанной зарплатой.
            professional_role: ID профессиональной роли (например, 112 — сетевой инженер).
            order_by: сортировка — "publication_time", "salary_desc", "salary_asc",
                      "relevance", "distance".

        Returns:
            Список словарей — вакансии из блока `organic` (или пустой список при ошибке).
        """
        params = {
            "text": query,
            "page": page,
            "items_on_page": items_on_page,
            "order_by": order_by,
        }

        if area:
            params["area"] = area
        if search_period:
            params["search_period"] = search_period
        if search_field:
            params["search_field"] = search_field
        if experience:
            params["experience"] = experience
        if employment_form:
            params["employment_form"] = employment_form
        if work_format:
            params["work_format"] = work_format
        if excluded_text:
            params["excluded_text"] = excluded_text
        if salary:
            params["salary"] = salary
        if only_with_salary:
            params["only_with_salary"] = "true"
        if professional_role:
            params["professional_role"] = professional_role

        try:
            r = self.session.get(HH_SEARCH, params=params, timeout=TIMEOUT)
            # print(f"[DEBUG] URL: {r.url}")
            r.raise_for_status()
            data = self._extract_state(r.text)
            result = data.get("vacancySearchResult", {})
            logger.info(
                f"totalResults={result.get('totalResults')}, "
                f"on page={len(result.get('vacancies', []))}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"HH search failed: {e}")
            return []

        return data.get("vacancySearchResult", {}).get("vacancies", [])

    def _get_detail(self, vacancy_id: int) -> dict | None:
        """
        Парсит страницу вакансии и возвращает dict с полями:
        description, key_skills, requirements_text.
        """
        time.sleep(1.5)
        try:
            r = self.session.get(f"{HH_BASE}/vacancy/{vacancy_id}", timeout=TIMEOUT)
            r.raise_for_status()
            data = self._extract_state(r.text)
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"HH detail failed for {vacancy_id}: {e}")
            return None

        vv = data.get("vacancyView")
        if not vv:
            logger.warning(f"No vacancyView for {vacancy_id}")
            return None

        desc_html = _find_key(vv, "description") or ""
        key_skills_raw = _find_key(vv, "keySkills") or []
        if isinstance(key_skills_raw, list):
            skills = [s for s in key_skills_raw if isinstance(s, str)]
        elif isinstance(key_skills_raw, dict):
            skills = key_skills_raw.get("keySkill", [])
        else:
            skills = []

        desc_text = BeautifulSoup(desc_html, "html.parser").get_text(
            separator="\n", strip=True
        )

        requirements = desc_text
        if skills:
            requirements += "\n\nКлючевые навыки: " + ", ".join(skills)

        return {
            "description": desc_text,
            "key_skills": skills,
            "requirements_text": requirements,
        }

    @staticmethod
    def _parse_salary(compensation: dict) -> str | None:
        """
        Преобразует compensation из hh.ru в читаемую строку.

        Example:
            {"from": 250000, "currencyCode": "RUR", "gross": False, "mode": "MONTH"}
            → "от 250000 ₽ в месяц (на руки)"
        """
        if not compensation or "noCompensation" in compensation:
            return None

        from_val = compensation.get("from")
        to_val = compensation.get("to")
        currency = compensation.get("currencyCode", "RUR")
        gross = compensation.get("gross", True)
        mode = compensation.get("mode", "MONTH")

        symbol = CURRENCY_SYMBOLS.get(currency, currency)

        if from_val and to_val:
            salary = f"от {from_val} до {to_val} {symbol}"
        elif from_val:
            salary = f"от {from_val} {symbol}"
        elif to_val:
            salary = f"до {to_val} {symbol}"
        else:
            return None

        mode_suffix = {
            "MONTH": " в месяц",
            "HOUR": " в час",
            "SHIFT": " за смену",
            "FLY_IN_FLY_OUT": " за вахту",
        }.get(mode, "")

        gross_suffix = " (до вычета)" if gross else " (на руки)"

        return salary + mode_suffix + gross_suffix

    def fetch_full(self, vacancy: dict) -> dict | None:
        """
        Принимает vacancy из search и возвращает готовый dict для БД.
        Внутри подтягивает detail. Возвращает None, если detail нет.
        """
        detail = self._get_detail(vacancy["vacancyId"])
        if not detail:
            return None

        wf = vacancy.get("workFormats") or []
        work_format = None
        if wf and isinstance(wf, list):
            elements = wf[0].get("workFormatsElement", [])
            work_format = ",".join(elements) if elements else None

        comp = vacancy.get("compensation") or {}
        has_comp = "noCompensation" not in comp and comp
        salary_from = comp.get("from") if has_comp else None
        salary_to = comp.get("to") if has_comp else None
        salary_currency = comp.get("currencyCode") if has_comp else None
        salary_gross = comp.get("gross") if has_comp else None

        role_obj = vacancy.get("professionalRoleIds") or []
        professional_role = None
        if role_obj and isinstance(role_obj, list):
            ids = role_obj[0].get("professionalRoleId", [])
            if ids:
                professional_role = ids[0]

        company = vacancy.get("company") or {}
        reviews = company.get("employerReviews") or {}
        employer_rating = reviews.get("totalRating")
        employer_reviews_count = reviews.get("reviewsCount")

        skills = detail.get("key_skills") or []

        return {
            "url": f"{HH_BASE}/vacancy/{vacancy['vacancyId']}",
            "name": vacancy.get("name"),
            "city": vacancy.get("area", {}).get("name"),
            "employer": company.get("name"),
            "employer_id": company.get("id"),
            "employer_rating": employer_rating,
            "employer_reviews_count": employer_reviews_count,
            "salary": self._parse_salary(comp),
            "salary_from": salary_from,
            "salary_to": salary_to,
            "salary_currency": salary_currency,
            "salary_gross": salary_gross,
            "requirements": detail.get("requirements_text"),
            "key_skills": ",".join(skills) if skills else None,
            "experience": vacancy.get("workExperience"),
            "work_format": work_format,
            "employment_form": vacancy.get("employmentForm"),
            "schedule": vacancy.get("@workSchedule"),
            "professional_role": professional_role,
            "published_at": vacancy.get("publicationTime", {}).get("$"),
            "responses_count": vacancy.get("totalResponsesCount"),
        }
