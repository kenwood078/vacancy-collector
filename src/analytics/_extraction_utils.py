"""Внутренние операции очистки ответов LLM."""

import re
from collections.abc import Callable
from typing import Any

MARKDOWN_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def _clean_json_response(raw: str) -> str:
    """Удаляет Markdown-обрамление ответа.

    Args:
        raw: исходный ответ LLM.

    Returns:
        Текст для разбора JSON без внешних пробелов и обрамления.
    """
    return MARKDOWN_FENCE.sub("", raw.strip()).strip()


def _clean_item(item: str) -> str:
    """Очищает элемент структурированного списка.

    Args:
        item: строка из ответа LLM.

    Returns:
        Строка без скобок, внешних кавычек и маркеров, с единичными пробелами.
    """
    item = re.sub(r"\s*\(.*?\)", "", item)
    item = item.strip().strip("-—•*").strip()
    item = item.strip("\"'«»").strip()
    item = re.sub(r"\s+", " ", item)
    return item.strip()


def _clean_list(value: Any, max_n: int, clean: Callable[[str], str]) -> list[str]:
    """Преобразует список JSON в ограниченный список очищенных строк.

    Args:
        value: произвольное значение JSON; значения кроме списков дают [].
        max_n: максимальное число непустых элементов.
        clean: функция очистки строкового представления элемента.

    Returns:
        Непустые строки в исходном порядке, обрезанные до max_n.
    """
    if not isinstance(value, list):
        return []
    cleaned = [clean(str(s)) for s in value if str(s).strip()]
    return [s for s in cleaned if s][:max_n]
