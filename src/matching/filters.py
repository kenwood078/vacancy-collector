"""Чистые проверки условий подбора без изменения векторного рейтинга."""

import re

_CURRENCY_CODES = frozenset(
    "RUB USD EUR KZT BYN BYR UAH AZN UZS KGS GEL AMD TJS GBP CHF CNY JPY AED TRY "
    "INR PLN AUD CAD SGD HKD ILS NOK SEK DKK THB VND KRW".split()
)
_CURRENCY_ALIASES = (
    (re.compile(r"₽|\bруб(?:лей|ля|ль)?\b", re.IGNORECASE), "RUB"),
    (
        re.compile(r"(?<![a-z])\$|\b(?:долл|доллар(?:ов|а|ы)?)\b", re.IGNORECASE),
        "USD",
    ),
    (re.compile(r"€|\bевро\b", re.IGNORECASE), "EUR"),
    (re.compile(r"₸", re.IGNORECASE), "KZT"),
)
_NON_MONTHLY_PERIOD = re.compile(
    r"\b(?:час(?:а|ов)?|ч|почасов\w*|смен\w*|вахт\w*|услуг\w*|"
    r"день|дня|дней|дн|сут\w*|год(?:а|ов)?|лет|г|недел\w*|нед|проект\w*|"
    r"hour(?:s|ly)?|hr|h|shift|day|daily|week(?:ly)?|year(?:ly)?|annual(?:ly)?|"
    r"service)\b",
    re.IGNORECASE,
)
_MONTHLY_PERIOD = re.compile(
    r"\b(?:месяц(?:а|ев)?|мес|month(?:ly)?|mo)\b", re.IGNORECASE
)


def _work_formats(value: str | None) -> set[str]:
    """Разбирает форматы через запятую, исключая пустые и unknown.

    Args:
        value: сохранённая строка форматов или None.

    Returns:
        Набор форматов в верхнем регистре.
    """
    return {
        part.strip().upper()
        for part in (value or "").split(",")
        if part.strip() and part.strip().upper() != "UNKNOWN"
    }


def _city(value: str | None) -> str:
    """Нормализует город без географических предположений.

    Args:
        value: город или None.

    Returns:
        Город без лишних пробелов и регистра; неизвестный город — пустая строка.
    """
    normalized = " ".join((value or "").casefold().split())
    return "" if normalized == "unknown" else normalized


def matches_work_location(resume: dict, vacancy: dict) -> bool:
    """Проверяет наличие допустимого сочетания формата и города.

    При неизвестном формате используется известная сторона: например,
    удалённое резюме не ограничивается городом вакансии без формата.
    Готовность к переезду снимает только географическое ограничение.

    Args:
        resume: сохранённые предпочтения, город и готовность к переезду.
        vacancy: форматы работы и город вакансии.

    Returns:
        False только при явном противоречии известных условий.
    """
    resume_formats = _work_formats(resume.get("work_format"))
    vacancy_formats = _work_formats(vacancy.get("work_format"))
    if resume_formats and vacancy_formats:
        common_formats = resume_formats & vacancy_formats
        if not common_formats:
            return False
    else:
        common_formats = resume_formats or vacancy_formats

    if resume.get("ready_to_relocate"):
        return True

    resume_city = _city(resume.get("city"))
    vacancy_city = _city(vacancy.get("city"))
    if not resume_city or not vacancy_city or resume_city == vacancy_city:
        return True

    return not common_formats or "REMOTE" in common_formats


def _currency(value: str | None) -> str | None:
    """Нормализует явный код валюты, не подставляя рубли по умолчанию.

    Args:
        value: код валюты из структурированного поля.

    Returns:
        Код валюты или None для неизвестного значения.
    """
    code = (value or "").strip().upper()
    if code == "RUR":
        code = "RUB"
    return code if code in _CURRENCY_CODES else None


def _expectation_currency(text: str | None) -> str | None:
    """Извлекает единственную явно указанную валюту ожиданий.

    Args:
        text: сохранённая строка зарплатных ожиданий.

    Returns:
        Код валюты или None, если обозначение отсутствует либо неоднозначно.
    """
    text = text or ""
    currencies = {
        code
        for token in re.findall(r"\b[a-z]{3}\b", text, re.IGNORECASE)
        if (code := _currency(token)) is not None
    }
    currencies.update(
        code for pattern, code in _CURRENCY_ALIASES if pattern.search(text)
    )
    return next(iter(currencies)) if len(currencies) == 1 else None


def _is_monthly(text: str | None, assume_monthly: bool = False) -> bool:
    """Проверяет период, не переводя другие ставки в месячную зарплату.

    Args:
        text: строка зарплаты.
        assume_monthly: считать отсутствие периода месячным для ожиданий резюме.

    Returns:
        True для месячной суммы без указаний на немесячный период.
    """
    text = text or ""
    if _NON_MONTHLY_PERIOD.search(text):
        return False
    return assume_monthly or bool(_MONTHLY_PERIOD.search(text))


def matches_salary(resume: dict, vacancy: dict) -> bool:
    """Исключает только явно недостаточную сопоставимую месячную зарплату.

    Налоги не пересчитываются. Разные или неизвестные валюты и немесячные
    ставки не сравниваются. Неизвестный период вакансии также не отсекает её;
    ожидания без периода считаются месячными.

    Args:
        resume: минимальные ожидания и их исходная строка.
        vacancy: верхняя граница, валюта и строка зарплаты вакансии.

    Returns:
        False, если сопоставимая верхняя граница ниже минимума кандидата.
    """
    salary_min = resume.get("salary_min")
    salary_to = vacancy.get("salary_to")
    if salary_min is None or salary_to is None:
        return True

    resume_currency = _expectation_currency(resume.get("salary_expectation"))
    vacancy_currency = _currency(vacancy.get("salary_currency"))
    if resume_currency is None or resume_currency != vacancy_currency:
        return True
    if not _is_monthly(resume.get("salary_expectation"), assume_monthly=True):
        return True
    if not _is_monthly(vacancy.get("salary")):
        return True
    return salary_to >= salary_min
