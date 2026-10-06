import argparse
import logging
import os
from datetime import datetime
from pathlib import Path

import json5
from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv

from src.analytics.llm_extractor import VacancyExtractor
from src.analytics.resume_extractor import ResumeExtractor
from src.matching.embedder import QwenEmbedder
from src.matching.embedding_text import build_resume_text, build_vacancy_text
from src.matching.match_report import build_match_report
from src.matching.matcher import match_resume
from src.matching.resume_parser import parse_resume
from src.storage import VacancyStorage
from src.tools.stats_tool import GetStatsTool

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
AGENTS_DIR = os.path.join(BASE_DIR, "agents")
CREW_CONFIG_PATH = os.path.join(BASE_DIR, "crew.jsonc")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
LLM_MODEL = os.getenv("LLM_MODEL", "openai/ornith-1.0-9b-mlx@8bit")
LLM_MODEL_EXTRACTOR = os.getenv("LLM_MODEL_EXTRACTOR", LLM_MODEL)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")

QUERY_SERPER = """
site:hh.ru/vacancy (intitle:"Network Engineer" OR intitle:"Сетевой инженер" OR intitle:"Network Architect" OR intitle:"Сетевой архитектор" OR intitle:"Сетевой администратор") (Москва OR "Санкт-Петербург") -архив -архиве -стажер -стажёр -junior -помощник -техподдержка -support
"""

QUERY_HH = '("Сетевой инженер" OR "Network Engineer" OR "Сетевой архитектор" OR "Network Architect" OR "Сетевой администратор" OR "NetOps" OR "Инженер по сетевой безопасности" OR "Инженер сетевой безопасности")'

AVAILABLE_TOOLS = {
    "GetStatsTool": GetStatsTool(),
}


def setup_logging() -> None:
    """Настраивает корневой логгер для CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def get_llm() -> LLM:
    """Создаёт экземпляр LLM, подключённый к локальному серверу.

    Returns:
        LLM для writer и сбора через Serper.
    """
    return LLM(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0.6,
    )


def get_extractor_llm() -> LLM:
    """LLM для извлечения данных — может отличаться от writer-модели.

    Returns:
        LLM для анализа вакансий и резюме.
    """
    return LLM(
        model=LLM_MODEL_EXTRACTOR,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0.2,
    )


def load_agent_config(agent_name: str) -> dict:
    """Загружает конфигурацию агента из agents/<name>.jsonc.

    Args:
        agent_name: имя файла конфигурации без расширения.

    Returns:
        Конфигурация агента из JSONC.
    """
    path = os.path.join(AGENTS_DIR, f"{agent_name}.jsonc")
    with open(path, "r", encoding="utf-8") as f:
        return json5.loads(f.read())


def load_crew_config() -> dict:
    """Загружает конфигурацию crew из crew.jsonc.

    Returns:
        Конфигурация CrewAI из JSONC.
    """
    with open(CREW_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json5.loads(f.read())


def build_agent(config: dict) -> Agent:
    """Создаёт CrewAI-агента по конфигу (tools, role, goal, backstory).

    Args:
        config: конфигурация агента.

    Returns:
        Агент с параметрами и инструментами из конфигурации.
    """
    tools = [
        AVAILABLE_TOOLS[t] for t in config.get("tools", []) if t in AVAILABLE_TOOLS
    ]
    settings = config.get("settings", {})
    return Agent(
        role=config["role"],
        goal=config["goal"],
        backstory=config["backstory"],
        llm=get_llm(),
        tools=tools,
        verbose=settings.get("verbose", False),
        allow_delegation=settings.get("allow_delegation", False),
        planning=settings.get("planning", False),
        max_iter=settings.get("max_iter", 50),
    )


def cmd_collect_serper(n: int, no_cache: bool = False) -> None:
    """Собирает n новых вакансий без использования агентов.

    Args:
        n: число новых вакансий для сбора.
        no_cache: отключить чтение и запись кэша поиска.
    """
    from src.collectors.pipeline import collect_serper

    added, errors, attempts = collect_serper(
        n_vacancies=n, query=QUERY_SERPER, llm=get_llm(), use_cache=not no_cache
    )
    print(f"\nСобрано: {added}, ошибок: {errors}, попыток: {attempts}")


def cmd_collect_hh(n: int) -> None:
    """Сбор n вакансий напрямую с hh.ru.

    Args:
        n: число новых вакансий для сбора.
    """
    from src.collectors.pipeline import collect_hh

    added, errors, attempts = collect_hh(
        n_vacancies=n,
        query=QUERY_HH,
        area=[1, 2],
        search_period=30,
        search_field=["name"],
        experience=["between1And3", "between3And6", "moreThan6"],
        work_format=["REMOTE", "HYBRID"],
        excluded_text="стажер junior помощник техподдержка support",
        only_with_salary=False,
        professional_role=112,
    )
    print(f"\n[hh] Собрано: {added}, ошибок: {errors}, попыток: {attempts}")


def _build_tasks(crew_config: dict, agents: dict[str, Agent]) -> list[Task]:
    """Создаёт задачи и связывает контекст в порядке конфигурации.

    Args:
        crew_config: конфигурация CrewAI.
        agents: агенты по именам из конфигурации.

    Returns:
        Задачи с назначенными агентами и контекстом.
    """
    tasks = []
    task_dict = {}
    for task_conf in crew_config["tasks"]:
        task = Task(
            description=task_conf["description"],
            expected_output=task_conf["expected_output"],
            agent=agents[task_conf["agent"]],
            markdown=task_conf.get("markdown", False),
        )
        tasks.append(task)
        task_dict[task_conf["name"]] = task

    for i, task_conf in enumerate(crew_config["tasks"]):
        if "context" in task_conf:
            tasks[i].context = [
                task_dict[n] for n in task_conf["context"] if n in task_dict
            ]
        elif i > 0:
            tasks[i].context = [tasks[i - 1]]

    return tasks


def _save_task_outputs(
    tasks: list[Task], crew_config: dict, timestamp: str
) -> list[str]:
    """Сохраняет непустые результаты задач и возвращает пути файлов.

    Args:
        tasks: задачи в порядке конфигурации.
        crew_config: конфигурация CrewAI.
        timestamp: метка времени для имён выходных файлов.

    Returns:
        Пути сохранённых файлов в порядке задач.
    """
    saved_files = []
    for i, task in enumerate(tasks):
        if not task.output:
            logger.warning("Task %s returned no output", i + 1)
            continue
        task_name = crew_config["tasks"][i]["name"]
        filename = (
            f"report_{timestamp}.md"
            if task_name == "analysis_task"
            else f"task_{i}_{timestamp}.txt"
        )
        filepath = os.path.join(OUTPUTS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(task.output.raw)
        saved_files.append(filepath)
        logger.info("Saved: %s", filepath)

    return saved_files


def cmd_report() -> None:
    """Запускает Crew с writer-агентом и сохраняет отчёт в outputs/."""
    # Сохраняем локальное время и прежний формат даты.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    crew_config = load_crew_config()

    agents = {
        name: build_agent(load_agent_config(name)) for name in crew_config["agents"]
    }

    tasks = _build_tasks(crew_config, agents)

    process_type = (
        Process.sequential
        if crew_config.get("process") == "sequential"
        else Process.hierarchical
    )
    crew = Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=process_type,
        verbose=crew_config.get("verbose", True),
        memory=crew_config.get("memory", False),
        cache=crew_config.get("cache", True),
        max_rpm=crew_config.get("max_rpm", None),
    )

    logger.info("Crew execution started")
    result = crew.kickoff()

    logger.info("Usage metrics: %s", crew.usage_metrics)

    saved_files = _save_task_outputs(tasks, crew_config, timestamp)

    print("\n" + "=" * 60)
    if saved_files:
        print("Сохранённые файлы:")
        for f in saved_files:
            print(f" - {f}")
    else:
        print("Ни один файл не был сохранён")
    print("=" * 60)
    print(result)


def cmd_analyze(n: int | None = None) -> None:
    """Прогоняет необработанные вакансии через LLM-extractor и пишет в vacancy_analysis.

    Args:
        n: сколько вакансий обработать. None — все необработанные.
    """
    extractor = VacancyExtractor(get_extractor_llm())
    added = skipped = failed = 0

    with VacancyStorage() as storage:
        vacancies = storage.get_unanalyzed(limit=n)
        total = len(vacancies)
        if total == 0:
            print("Нет необработанных вакансий.")
            return

        print(f"К обработке: {total}")
        for i, v in enumerate(vacancies, start=1):
            result = extractor.extract(v)
            if result is None:
                skipped += 1
                logger.info("[%d/%d] skip: %s", i, total, v.get("id"))
                continue
            try:
                if storage.save_analysis(result):
                    added += 1
                    logger.info(
                        "[%d/%d] ok: id=%s stack=%d tasks=%d",
                        i,
                        total,
                        v["id"],
                        len(result["stack"]),
                        len(result["tasks"]),
                    )
                else:
                    failed += 1
            except Exception as e:  # noqa: BLE001 -- сохранить обработку всех ошибок операции
                logger.error("[%d/%d] save failed id=%s: %s", i, total, v["id"], e)
                failed += 1

    print(f"\nГотово: обработано {added}, пропущено {skipped}, ошибок {failed}")


def cmd_embed_vacancies(n: int | None = None) -> None:
    """Считает эмбеддинги для вакансий, у которых их ещё нет.

    Args:
        n: сколько обработать. None — все.
    """
    embedder = QwenEmbedder()
    added = failed = 0

    with VacancyStorage() as storage:
        rows = storage.get_unembedded(limit=n)
        total = len(rows)
        if total == 0:
            print("Нет вакансий без эмбеддинга.")
            return

        print(f"К обработке: {total}")
        for i, row in enumerate(rows, start=1):
            text = build_vacancy_text(row)
            try:
                vec = embedder.embed_document(text)
                storage.save_embedding(
                    vacancy_id=row["vacancy_id"],
                    embedding_text=text,
                    embedding=vec,
                    model=embedder.model,
                )
                added += 1
                logger.info(
                    "[%d/%d] ok: id=%s dim=%d",
                    i,
                    total,
                    row["vacancy_id"],
                    len(vec),
                )
            except Exception as e:  # noqa: BLE001 -- сохранить обработку всех ошибок операции
                failed += 1
                logger.error(
                    "[%d/%d] failed id=%s: %s",
                    i,
                    total,
                    row["vacancy_id"],
                    e,
                )

    print(f"\nГотово: {added}, ошибок: {failed}")


def cmd_save_resume(path: str) -> None:
    """Читает резюме, извлекает поля, считает эмбеддинг, сохраняет.

    Args:
        path: путь к файлу резюме.
    """
    text = parse_resume(path)
    print(f"Резюме: {Path(path).name} ({len(text)} chars)")

    extractor = ResumeExtractor(get_extractor_llm())
    analysis = extractor.extract(text)
    if analysis is None:
        print("Не удалось извлечь данные из резюме.")
        return

    print(f"role: {analysis['role']}")
    print(f"city: {analysis['city']}, work_format: {analysis['work_format']}")
    print(f"experience: {analysis['experience_years']} лет")
    print(
        f"salary: {analysis['salary_expectation']} "
        f"({analysis['salary_min']}–{analysis['salary_max']})"
    )
    print(f"stack: {len(analysis['stack'])}, tasks: {len(analysis['tasks'])}")
    print(f"english: {analysis['english_level']}")

    embedder = QwenEmbedder()
    embedding_text = build_resume_text(analysis)
    embedding = embedder.embed_query(embedding_text)

    with VacancyStorage() as storage:
        resume_id = storage.save_resume(
            title=Path(path).name,
            source_text=text,
            analysis=analysis,
            embedding_text=embedding_text,
            embedding=embedding,
            model=embedder.model,
        )

    print(f"\nСохранено: resume_id={resume_id}")


def _fmt_list(items: list[str] | None) -> str:
    """Склеивает список через запятую; пустое → '—'.

    Args:
        items: список строк или None.

    Returns:
        Строка с элементами через запятую или «—».
    """
    if not items:
        return "—"
    return ", ".join(items)


def _print_match(i: int, m: dict) -> None:
    """Выводит одну найденную вакансию в прежнем формате CLI.

    Args:
        i: номер вакансии, начиная с 1.
        m: словарь вакансии с оценкой совпадения.
    """
    name = m.get("name") or "—"
    employer = m.get("employer") or "—"
    city = m.get("city") or "—"
    exp = m.get("experience") or "—"
    wf = m.get("work_format") or "—"
    salary = m.get("salary") or "—"
    english = m.get("english_level") or "unknown"
    domains = _fmt_list(m.get("domains"))
    certs = _fmt_list(m.get("certifications"))
    langs = _fmt_list(m.get("programming_languages"))
    url = m.get("url") or "—"

    print(f"#{i}  score {m['score']}  {name}")
    print(f"    {employer} · {city}")
    print(f"    Опыт: {exp} · Формат: {wf}")
    print(f"    Зарплата: {salary} · Английский: {english}")
    print(f"    Домены: {domains}")
    print(f"    Сертификации: {certs} · Языки: {langs}")
    print(f"    {url}")
    print()


def cmd_match(resume_id: int, top_n: int = 20) -> None:
    """Векторный матчинг: резюме → top-N вакансий.

    Args:
        resume_id: ID резюме.
        top_n: сколько вакансий показать.
    """
    resume, matches = match_resume(resume_id, top_n=top_n)

    print(f"\nРезюме #{resume['id']}: {resume.get('role') or '—'}")
    print(f"Стек: {', '.join(resume.get('stack') or [])[:120]}")
    print(f"Опыт: {resume.get('experience_years')} лет")
    print(f"Город: {resume.get('city')}, переезд: {resume.get('ready_to_relocate')}")
    print(f"work_format: {resume.get('work_format')}")
    print(f"Найдено: {len(matches)} вакансий\n")

    for i, m in enumerate(matches, start=1):
        _print_match(i, m)
        md = build_match_report(resume, matches)
        # Сохраняем локальное время и прежний формат даты.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        path = os.path.join(OUTPUTS_DIR, f"match_resume_{resume_id}_{ts}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\nОтчёт: {path}")


def cmd_all_serper(n: int, no_cache: bool = False) -> None:
    """Сбор вакансий serper + генерация отчёта.

    Args:
        n: число новых вакансий для сбора.
        no_cache: отключить чтение и запись кэша поиска.
    """
    cmd_collect_serper(n, no_cache=no_cache)
    cmd_report()


def cmd_all_hh(n: int) -> None:
    """Сбор вакансий hh + генерация отчёта.

    Args:
        n: число новых вакансий для сбора.
    """
    cmd_collect_hh(n)
    cmd_report()


def main() -> None:
    """Разбирает аргументы CLI и запускает выбранную команду."""
    setup_logging()
    parser = argparse.ArgumentParser(description="Collector & Reporter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_hh = sub.add_parser("collect-hh", help="Сбор напрямую с hh.ru")
    p_hh.add_argument("--n", type=int, default=10)

    p_serper = sub.add_parser("collect-serper", help="Сбор через Serper")
    p_serper.add_argument("--n", type=int, default=10)
    p_serper.add_argument("--no-cache", action="store_true")

    sub.add_parser("report", help="Сгенерировать отчёт по данным из БД")

    p_analyze = sub.add_parser(
        "analyze",
        help="Извлечь структурированные данные из вакансий через LLM",
    )
    p_analyze.add_argument(
        "--n",
        type=int,
        default=None,
        help="Сколько вакансий обработать (по умолчанию — все необработанные)",
    )

    p_embed = sub.add_parser("embed-vacancies", help="Посчитать эмбеддинги вакансий")
    p_embed.add_argument("--n", type=int, default=None)

    p_resume = sub.add_parser("save-resume", help="Загрузить и сохранить резюме")
    p_resume.add_argument("--path", type=str, required=True, help="Путь к файлу резюме")

    p_match = sub.add_parser("match", help="Найти top-N вакансий под резюме")
    p_match.add_argument("--resume-id", type=int, required=True)
    p_match.add_argument("--top", type=int, default=20)

    p_all_hh = sub.add_parser("all-hh", help="Сбор + отчет")
    p_all_hh.add_argument("--n", type=int, default=10)

    p_all_serper = sub.add_parser("all-serper", help="Сбор + отчет")
    p_all_serper.add_argument("--n", type=int, default=10)
    p_all_serper.add_argument("--no-cache", action="store_true")

    args = parser.parse_args()

    if args.command == "collect-serper":
        cmd_collect_serper(args.n, no_cache=args.no_cache)
    elif args.command == "collect-hh":
        cmd_collect_hh(args.n)
    elif args.command == "report":
        cmd_report()
    elif args.command == "analyze":
        cmd_analyze(args.n)
    elif args.command == "embed-vacancies":
        cmd_embed_vacancies(args.n)
    elif args.command == "save-resume":
        cmd_save_resume(args.path)
    elif args.command == "match":
        cmd_match(args.resume_id, top_n=args.top)
    elif args.command == "all-serper":
        cmd_all_serper(args.n, no_cache=args.no_cache)
    elif args.command == "all-hh":
        cmd_all_hh(args.n)


if __name__ == "__main__":
    main()
