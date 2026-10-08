"""Загрузка фильтров HH и профилей отчётов из JSONC."""

import re
from pathlib import Path
from typing import Any

import json5

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
EXPERIENCES = {"noExperience", "between1And3", "between3And6", "moreThan6"}
WORK_FORMATS = {"ON_SITE", "REMOTE", "HYBRID", "FIELD_WORK"}


class SpecializationConfigError(ValueError):
    """Ошибка специализации или её конфигурации."""


def _read_jsonc(path: Path) -> dict:
    """Читает объект JSONC с диагностикой пути.

    Args:
        path: путь конфигурации.

    Returns:
        Прочитанный словарь.

    Raises:
        SpecializationConfigError: файл недоступен или содержит неверный JSONC.
    """
    try:
        data = json5.loads(path.read_text(encoding="utf-8"), allow_duplicate_keys=False)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SpecializationConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecializationConfigError(f"{path}: ожидается объект JSONC")
    return data


def _require(valid: bool, location: str, field: str, expected: str) -> None:
    """Проверяет условие для поля конфигурации.

    Args:
        valid: результат проверки.
        location: файл и специализация.
        field: имя поля.
        expected: описание допустимого значения.

    Raises:
        SpecializationConfigError: значение не соответствует условию.
    """
    if not valid:
        raise SpecializationConfigError(f"{location}: поле {field}: {expected}")


def _is_string_list(value: Any) -> bool:
    """Проверяет непустой список непустых строк.

    Args:
        value: значение из JSONC.

    Returns:
        True, если список содержит только непустые строки.
    """
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def load_specialization(spec: str) -> dict:
    """Загружает и проверяет фильтры выбранной специализации.

    Args:
        spec: ключ специализации, без значения по умолчанию.

    Returns:
        Фильтры HH и название специализации.

    Raises:
        SpecializationConfigError: неизвестный ключ или неверные фильтры.
    """
    path = CONFIG_DIR / "specializations.jsonc"
    configurations = _read_jsonc(path)
    if spec not in configurations:
        available = ", ".join(configurations)
        raise SpecializationConfigError(
            f"{path}: неизвестная специализация {spec!r}; доступны: {available}"
        )
    location = f"{path} [{spec}]"
    _require(
        re.fullmatch(r"[a-z][a-z0-9_]*", spec) is not None,
        location,
        "spec",
        "ожидается ключ из латинских букв, цифр и подчёркиваний",
    )
    config = configurations[spec]
    _require(isinstance(config, dict), location, spec, "ожидается объект")
    for field in ("display_name", "query_hh"):
        value = config.get(field)
        _require(
            isinstance(value, str) and bool(value.strip()),
            location,
            field,
            "ожидается непустая строка",
        )
    role = config.get("professional_role")
    _require(
        type(role) is int and role > 0,
        location,
        "professional_role",
        "ожидается положительное целое число",
    )
    area = config.get("area")
    _require(
        isinstance(area, list)
        and bool(area)
        and all(type(item) is int and item > 0 for item in area),
        location,
        "area",
        "ожидается непустой список положительных целых кодов регионов",
    )
    for field, allowed in (("experience", EXPERIENCES), ("work_format", WORK_FORMATS)):
        value = config.get(field)
        _require(
            _is_string_list(value) and set(value) <= allowed,
            location,
            field,
            f"ожидается непустой список значений из {', '.join(sorted(allowed))}",
        )
    _require(
        isinstance(config.get("excluded_text"), str),
        location,
        "excluded_text",
        "ожидается строка (может быть пустой)",
    )
    period = config.get("search_period")
    _require(
        type(period) is int and 1 <= period <= 30,
        location,
        "search_period",
        "ожидается целое число от 1 до 30 дней",
    )
    return config


def load_report_profile(spec: str) -> dict:
    """Загружает профиль writer, задачи и словари отчёта.

    Args:
        spec: ключ специализации.

    Returns:
        Профиль с непустым списком skills_keywords из JSONC.

    Raises:
        SpecializationConfigError: профиль отсутствует или содержит неверные поля.
    """
    load_specialization(spec)
    path = CONFIG_DIR / "report_profiles" / f"{spec}.jsonc"
    profile = _read_jsonc(path)
    location = f"{path} [{spec}]"
    for section, fields in (
        ("writer", ("role", "goal", "backstory")),
        ("task", ("description", "expected_output")),
    ):
        value = profile.get(section)
        _require(isinstance(value, dict), location, section, "ожидается объект")
        for field in fields:
            item = value.get(field)
            _require(
                isinstance(item, str) and bool(item.strip()),
                location,
                f"{section}.{field}",
                "ожидается непустая строка",
            )
    _require(
        "skills_keywords" in profile,
        location,
        "skills_keywords",
        "обязательное поле",
    )
    keywords = profile["skills_keywords"]
    _require(
        _is_string_list(keywords),
        location,
        "skills_keywords",
        "ожидается непустой список строк",
    )
    groups = profile.get("skill_groups")
    _require(
        isinstance(groups, dict) and bool(groups),
        location,
        "skill_groups",
        "ожидается непустой объект: название группы → список терминов",
    )
    for name, terms in groups.items():
        _require(
            bool(name.strip()) and _is_string_list(terms),
            location,
            f"skill_groups.{name}",
            "ожидаются непустое название группы и непустой список строк",
        )
    return profile
