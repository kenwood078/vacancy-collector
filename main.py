import argparse
import logging
import os
from datetime import datetime
from pathlib import Path

import json5
from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import BaseTool
from dotenv import load_dotenv

from src.analytics.llm_extractor import VacancyExtractor
from src.analytics.resume_extractor import ResumeExtractor
from src.matching.embedder import QwenEmbedder
from src.matching.embedding_text import build_resume_text, build_vacancy_text
from src.matching.match_report import build_match_report
from src.matching.matcher import match_resume
from src.matching.resume_parser import parse_resume
from src.specializations import (
    SpecializationConfigError,
    load_report_profile,
    load_specialization,
)
from src.storage import VacancyStorage
from src.tools.stats_tool import GetStatsTool

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
AGENTS_DIR = os.path.join(BASE_DIR, "agents")
CREW_CONFIG_PATH = os.path.join(BASE_DIR, "crew.jsonc")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/ornith-1.0-9b-mlx@8bit")
LLM_MODEL_EXTRACTOR = os.getenv("LLM_MODEL_EXTRACTOR", LLM_MODEL)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")

QUERY_SERPER = """
site:hh.ru/vacancy (intitle:"Network Engineer" OR intitle:"Сетевой инженер" OR intitle:"Network Architect" OR intitle:"Сетевой архитектор" OR intitle:"Сетевой администратор") (Москва OR "Санкт-Петербург") -архив -архиве -стажер -стажёр -junior -помощник -техподдержка -support
"""


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


def build_agent(
    config: dict, available_tools: dict[str, BaseTool] | None = None
) -> Agent:
    """Создаёт CrewAI-агента по конфигу (tools, role, goal, backstory).

    Args:
        config: конфигурация агента.
        available_tools: инструменты текущего запуска; None создаёт новые экземпляры.

    Returns:
        Агент с параметрами и инструментами из конфигурации.
    """
    if available_tools is None:
        available_tools = {"GetStatsTool": GetStatsTool()}
    tools = [
        available_tools[name]
        for name in config.get("tools", [])
        if name in available_tools
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


def cmd_collect_hh(n: int, spec: str) -> None:
    """Собирает n вакансий выбранной специализации напрямую с hh.ru.

    Args:
        n: число новых вакансий для сбора.
        spec: обязательный ключ специализации.
    """
    config = load_specialization(spec)
    from src.collectors.pipeline import collect_hh

    added, errors, attempts = collect_hh(
        n_vacancies=n,
        query=config["query_hh"],
        area=config["area"],
        search_period=config["search_period"],
        search_field=["name"],
        experience=config["experience"],
        work_format=config["work_format"],
        excluded_text=config["excluded_text"],
        only_with_salary=False,
        professional_role=config["professional_role"],
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
    tasks: list[Task], crew_config: dict, timestamp: str, spec: str
) -> list[str]:
    """Сохраняет непустые результаты задач и возвращает пути файлов.

    Args:
        tasks: задачи в порядке конфигурации.
        crew_config: конфигурация CrewAI.
        timestamp: метка времени для имён выходных файлов.
        spec: специализация в имени отчёта.

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
            f"report_{spec}_{timestamp}.md"
            if task_name == "analysis_task"
            else f"task_{spec}_{i}_{timestamp}.txt"
        )
        filepath = os.path.join(OUTPUTS_DIR, filename)
        os.makedirs(OUTPUTS_DIR, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(task.output.raw)
        saved_files.append(filepath)
        logger.info("Saved: %s", filepath)

    return saved_files


def _validate_report_setup(crew_config: dict, agent_configs: dict[str, dict]) -> None:
    """Проверяет связи задач, агентов и инструмента статистики.

    Args:
        crew_config: конфигурация CrewAI с задачами выбранного профиля.
        agent_configs: конфигурации агентов по именам.

    Raises:
        ValueError: задачи или агенты отсутствуют либо некорректно связаны.
        KeyError: отсутствует обязательное поле или агент writer.
    """
    if not agent_configs or not crew_config["tasks"]:
        raise ValueError("agents и tasks не должны быть пустыми")
    for task in crew_config["tasks"]:
        if not isinstance(task.get("name"), str) or not task["name"].strip():
            raise ValueError("tasks.name должен быть непустой строкой")
        if task["agent"] not in agent_configs:
            raise ValueError(f"неизвестный агент задачи {task['name']!r}")
    if "GetStatsTool" not in agent_configs["writer"].get("tools", []):
        raise ValueError("writer.tools должен содержать GetStatsTool")


def _load_report_configuration(
    spec: str,
) -> tuple[dict, dict, dict, dict[str, dict]]:
    """Проверяет и объединяет конфигурации до подключения к сервисам.

    Args:
        spec: ключ специализации.

    Returns:
        Фильтры, профиль отчёта, конфигурация CrewAI и конфигурации агентов.

    Raises:
        SpecializationConfigError: конфигурация отчёта некорректна.
    """
    specialization = load_specialization(spec)
    profile = load_report_profile(spec)
    try:
        crew_config = load_crew_config()
        writer_profile = {
            field: profile["writer"][field] for field in ("role", "goal", "backstory")
        }
        agent_configs = {
            name: {**load_agent_config(name), **writer_profile}
            for name in crew_config["agents"]
        }
        task_profile = {
            field: profile["task"][field]
            for field in ("description", "expected_output")
        }
        crew_config["tasks"] = [
            {**task, **task_profile} for task in crew_config["tasks"]
        ]
        _validate_report_setup(crew_config, agent_configs)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise SpecializationConfigError(
            f"{CREW_CONFIG_PATH}, {AGENTS_DIR} [{spec}]: {exc}"
        ) from exc
    return specialization, profile, crew_config, agent_configs


def cmd_report(spec: str) -> None:
    """Готовит статистику специализации и запускает её writer-агента.

    Args:
        spec: обязательный ключ специализации.
    """
    specialization, profile, crew_config, agent_configs = _load_report_configuration(
        spec
    )
    stats_tool = GetStatsTool(
        specialization=spec,
        display_name=specialization["display_name"],
        professional_role=specialization["professional_role"],
        skills_keywords=profile["skills_keywords"],
        skill_groups=profile["skill_groups"],
    )
    if not stats_tool.prepare():
        print(
            f"Нет вакансий для специализации {spec} ({specialization['display_name']})."
        )
        return

    # Сохраняем локальное время и прежний формат даты.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    available_tools = {"GetStatsTool": stats_tool}
    agents = {
        name: build_agent(config, available_tools)
        for name, config in agent_configs.items()
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

    saved_files = _save_task_outputs(tasks, crew_config, timestamp, spec)

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
                saved = storage.save_embedding(
                    vacancy_id=row["vacancy_id"],
                    embedding_text=text,
                    embedding=vec,
                    model=embedder.model,
                )
                if not saved:
                    failed += 1
                    logger.error(
                        "[%d/%d] save did not update id=%s",
                        i,
                        total,
                        row["vacancy_id"],
                    )
                    continue
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
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\nОтчёт: {path}")


def cmd_all_hh(n: int, spec: str) -> None:
    """Собирает вакансии HH и строит отчёт той же специализации.

    Args:
        n: число новых вакансий для сбора.
        spec: обязательный ключ специализации.
    """
    _load_report_configuration(spec)
    cmd_collect_hh(n, spec)
    cmd_report(spec)


def _build_parser() -> argparse.ArgumentParser:
    """Создаёт CLI-парсер с командами и их аргументами.

    Returns:
        Парсер восьми команд с обязательной специализацией для HH и report.
    """
    parser = argparse.ArgumentParser(description="Collector & Reporter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_hh = sub.add_parser("collect-hh", help="Сбор напрямую с hh.ru")
    p_hh.add_argument("--n", type=int, default=10)
    _add_spec_argument(p_hh)

    p_serper = sub.add_parser("collect-serper", help="Сбор через Serper")
    p_serper.add_argument("--n", type=int, default=10)
    p_serper.add_argument("--no-cache", action="store_true")

    p_report = sub.add_parser("report", help="Отчёт по специализации из БД")
    _add_spec_argument(p_report)

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
    _add_spec_argument(p_all_hh)

    return parser


def _add_spec_argument(parser: argparse.ArgumentParser) -> None:
    """Добавляет обязательный ключ специализации без чтения конфига.

    Args:
        parser: парсер команды сбора или отчёта.
    """
    parser.add_argument(
        "--spec",
        required=True,
        help="Специализация: network_engineer, devops_sre, security",
    )


def main() -> None:
    """Разбирает аргументы CLI и запускает выбранную команду."""
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "collect-serper":
            cmd_collect_serper(args.n, no_cache=args.no_cache)
        elif args.command == "collect-hh":
            cmd_collect_hh(args.n, args.spec)
        elif args.command == "report":
            cmd_report(args.spec)
        elif args.command == "analyze":
            cmd_analyze(args.n)
        elif args.command == "embed-vacancies":
            cmd_embed_vacancies(args.n)
        elif args.command == "save-resume":
            cmd_save_resume(args.path)
        elif args.command == "match":
            cmd_match(args.resume_id, top_n=args.top)
        elif args.command == "all-hh":
            cmd_all_hh(args.n, args.spec)
    except SpecializationConfigError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
