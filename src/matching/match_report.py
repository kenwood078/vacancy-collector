"""Markdown-отчёт по матчингу резюме с вакансиями."""

from datetime import datetime


def format_vacancy_status(vacancy: dict) -> str:
    """Форматирует актуальность и время проверки для отчёта и CLI.

    Args:
        vacancy: запись с необязательными status и last_checked_at.

    Returns:
        Подпись статуса с датой либо отметкой об отсутствии проверки.
    """
    label = {
        "active": "Активна",
        "archived": "В архиве",
    }.get(vacancy.get("status"), "Актуальность не подтверждена")
    checked_at = vacancy.get("last_checked_at")
    date = checked_at.strftime("%Y-%m-%d %H:%M %z") if checked_at else "не выполнялась"
    return f"{label}; проверка: {date}"


def _fmt_list(items: list[str] | None, empty: str = "—") -> str:
    """Склеивает список через запятую; пустое → '—'.

    Args:
        items: список строк или None.
        empty: текст для пустого списка.

    Returns:
        Строка с элементами через запятую или значение empty.
    """
    if not items:
        return empty
    return ", ".join(items)


def _stack_overlap(resume_stack: list[str], vacancy_stack: list[str]) -> list[str]:
    """Возвращает пересечение двух стеков (case-insensitive),
    сохраняя оригинальное написание из резюме.

    Args:
        resume_stack: стек резюме или None.
        vacancy_stack: стек вакансии или None.

    Returns:
        Уникальные совпадения в порядке и написании резюме.

    Examples:
        resume = ["Cisco", "BGP", "Python"]
        vacancy = ["cisco", "ospf", "python"]
        → ["Cisco", "Python"]
    """
    return _overlap(resume_stack, vacancy_stack)


def _domain_overlap(
    resume_domains: list[str] | None, vacancy_domains: list[str] | None
) -> list[str]:
    """Возвращает пересечение доменов без учёта регистра.

    Args:
        resume_domains: домены резюме или None.
        vacancy_domains: домены вакансии или None.

    Returns:
        Уникальные совпадения в порядке и написании резюме.
    """
    return _overlap(resume_domains, vacancy_domains)


def _overlap(
    resume_items: list[str] | None, vacancy_items: list[str] | None
) -> list[str]:
    """Сохраняет порядок и написание резюме, исключая повторные совпадения.

    Args:
        resume_items: элементы резюме или None.
        vacancy_items: элементы вакансии или None.

    Returns:
        Уникальные совпадения в порядке и написании резюме.
    """
    if not resume_items or not vacancy_items:
        return []
    vacancy_lower = {s.lower() for s in vacancy_items}
    seen = set()
    result = []
    for s in resume_items:
        key = s.lower()
        if key in vacancy_lower and key not in seen:
            result.append(s)
            seen.add(key)
    return result


def _build_resume_header(resume: dict) -> list[str]:
    """Шапка с параметрами резюме.

    Args:
        resume: словарь с полями резюме.

    Returns:
        Строки раздела резюме в Markdown.
    """
    role = resume.get("role") or "—"
    experience = resume.get("experience_years")
    experience_str = f"{experience} лет" if experience is not None else "—"
    city = resume.get("city") or "—"
    relocate = "да" if resume.get("ready_to_relocate") else "нет"
    wf = resume.get("work_format") or "—"
    salary = resume.get("salary_expectation") or "—"

    stack = resume.get("stack") or []
    domains = resume.get("domains") or []

    return [
        f"**Роль:** {role}",
        f"**Опыт:** {experience_str}",
        f"**Город:** {city} (готов к переезду: {relocate})",
        f"**Формат работы:** {wf}",
        f"**Зарплатные ожидания:** {salary}",
        f"**Английский:** {resume.get('english_level') or 'unknown'}",
        "",
        f"**Домены:** {_fmt_list(domains)}",
        "",
        f"**Стек ({len(stack)}):**",
        _fmt_list(stack),
    ]


def _build_matches_table(matches: list[dict]) -> list[str]:
    """Таблица top-N вакансий.

    Args:
        matches: вакансии с оценками совпадения в порядке поиска.

    Returns:
        Строки Markdown-таблицы, включая заголовок.
    """
    lines = [
        "| # | Score | Название | Работодатель · рейтинг | Город | Формат | Опыт | Зарплата | Актуальность |",
        "|---|-------|----------|------------------------|-------|--------|------|----------|--------------|",
    ]
    for i, m in enumerate(matches, start=1):
        name = (m.get("name") or "—").replace("|", "\\|")
        employer = (m.get("employer") or "—").replace("|", "\\|")
        employer_rating = m.get("employer_rating")
        rating = f"★ {employer_rating:.1f}" if employer_rating is not None else "—"
        reviews_count = m.get("employer_reviews_count")
        if reviews_count is not None:
            rating += f" ({reviews_count} отзывов)"
        employer = f"{employer} · {rating}"
        city = m.get("city") or "—"
        wf = m.get("work_format") or "—"
        exp = m.get("experience") or "—"
        salary = (m.get("salary") or "—").replace("|", "\\|")
        url = m.get("url") or ""
        if url:
            name = name.replace("[", "\\[").replace("]", "\\]")
            name = f"[{name}]({url})"
        status = format_vacancy_status(m)

        lines.append(
            f"| {i} | {m['score']} | {name} | {employer} | {city} | "
            f"{wf} | {exp} | {salary} | {status} |"
        )
    return lines


def _build_top3_breakdown(
    resume: dict, matches: list[dict], top_n: int = 3
) -> list[str]:
    """Разбор топ-3 вакансий: пересечение стека и доменов.

    Args:
        resume: словарь с полями резюме.
        matches: вакансии с оценками совпадения в порядке поиска.
        top_n: максимальное число результатов.

    Returns:
        Строки разбора первых top_n вакансий.
    """
    resume_stack = resume.get("stack") or []
    resume_domains = resume.get("domains") or []

    lines = ["## Разбор топ-3", ""]

    for i, m in enumerate(matches[:top_n], start=1):
        name = m.get("name") or "—"
        employer = m.get("employer") or "—"
        url = m.get("url") or ""
        domains = m.get("domains") or []
        certs = m.get("certifications") or []
        vacancy_stack = m.get("stack") or []

        overlap_stack = _stack_overlap(resume_stack, vacancy_stack)
        overlap_domains = _domain_overlap(resume_domains, domains)

        lines.append(f"### {i}. {name} — {employer} ({m['score']})")
        lines.append("")
        if url:
            lines.append(f"- **Ссылка:** {url}")
        lines.append(f"- **Актуальность:** {format_vacancy_status(m)}")
        lines.append(f"- **Опыт:** {m.get('experience') or '—'}")
        lines.append(f"- **Формат:** {m.get('work_format') or '—'}")
        lines.append(f"- **Зарплата:** {m.get('salary') or '—'}")
        lines.append(f"- **Домены вакансии:** {_fmt_list(domains)}")

        if overlap_domains:
            lines.append(f"- **Совпадающие домены:** {_fmt_list(overlap_domains)}")
        else:
            lines.append("- **Совпадающие домены:** нет")

        if certs:
            lines.append(f"- **Требуются сертификаты:** {_fmt_list(certs)}")

        if overlap_stack:
            lines.append(
                f"- **Совпадает стек ({len(overlap_stack)}):** "
                f"{_fmt_list(overlap_stack)}"
            )
        else:
            lines.append("- **Совпадает стек:** нет прямых совпадений")

        lines.append("")

    return lines


def _build_summary(matches: list[dict]) -> list[str]:
    """Сводка: средний score, разброс.

    Args:
        matches: вакансии с оценками совпадения в порядке поиска.

    Returns:
        Строки сводки оценок или сообщения о пустом результате.
    """
    if not matches:
        return ["## Сводка", "", "Нет вакансий для анализа."]

    scores = [m["score"] for m in matches]
    avg = sum(scores) / len(scores)
    best = max(scores)
    worst = min(scores)

    return [
        "## Сводка",
        "",
        f"- **Вакансий в отчёте:** {len(matches)}",
        f"- **Средний score:** {avg:.4f}",
        f"- **Лучший score:** {best}",
        f"- **Худший score:** {worst}",
        f"- **Разброс:** {best - worst:.4f}",
    ]


def build_match_report(resume: dict, matches: list[dict]) -> str:
    """Собирает Markdown-отчёт по матчингу резюме.

    Args:
        resume: строка из таблицы resumes.
        matches: список вакансий от find_top_vacancies.

    Returns:
        Markdown-текст отчёта.
    """
    resume_id = resume.get("id", "?")
    # Сохраняем локальное время и прежний формат даты.
    now = datetime.now().strftime("%Y-%m-%d %H:%M")  # noqa: DTZ005

    lines: list[str] = [
        f"# Подбор вакансий под резюме #{resume_id}",
        "",
        f"Дата: {now}",
        "",
        "## Резюме",
        "",
    ]

    lines.extend(_build_resume_header(resume))
    lines.append("")

    lines.append("## Результат")
    lines.append("")
    lines.append(f"- **Прошли фильтры:** {len(matches)}")
    lines.append("")

    if not matches:
        lines.append("По заданным фильтрам вакансий не найдено.")
        return "\n".join(lines)

    lines.append("## Топ вакансий")
    lines.append("")
    lines.extend(_build_matches_table(matches))
    lines.append("")

    lines.extend(_build_top3_breakdown(resume, matches))
    lines.extend(_build_summary(matches))

    return "\n".join(lines)
