"""Чтение текста резюме из файла."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".text"}


def parse_resume(path: str | Path) -> str:
    """Читает текст резюме из файла.

    Args:
        path: путь к файлу (.txt, .md, .text).

    Returns:
        Содержимое файла как строка.

    Raises:
        FileNotFoundError: если файла нет.
        ValueError: если расширение не поддерживается.
        OSError: если файл недоступен для чтения.
        UnicodeDecodeError: если содержимое не является UTF-8.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Resume not found: {p}")

    if p.suffix.lower() not in TEXT_EXTENSIONS:
        raise ValueError(
            f"Unsupported format: {p.suffix}. "
            f"Поддерживаются: {', '.join(sorted(TEXT_EXTENSIONS))}"
        )

    text = p.read_text(encoding="utf-8").strip()
    logger.info("Parsed resume %s: %d chars", p.name, len(text))
    return text
