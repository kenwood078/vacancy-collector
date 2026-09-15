import argparse
import logging
import os
from datetime import datetime

import json5
from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv

from src.tools.stats_tool import GetStatsTool

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
AGENTS_DIR = os.path.join(BASE_DIR, "agents")
CREW_CONFIG_PATH = os.path.join(BASE_DIR, "crew.jsonc")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.environ["OPENAI_API_KEY"] = "not-needed"

QUERY = """
site:hh.ru/vacancy (intitle:"Network Engineer" OR intitle:"Сетевой инженер" OR intitle:"Network Architect" OR intitle:"Сетевой архитектор" OR intitle:"Сетевой администратор") (Москва OR "Санкт-Петербург") (удаленно OR удалённо OR remote OR дистанционно OR "удаленная работа") -архив -архиве -стажер -стажёр -junior -помощник -техподдержка -support
"""

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
    """Создаёт экземпляр LLM, подключённый к локальному серверу."""
    return LLM(
        model="ornith-1.0-9b-mlx@8bit",
        base_url="http://localhost:1234/v1",
        api_key="not-needed",
        temperature=0.6,
    )


def load_agent_config(agent_name: str) -> dict:
    """Загружает конфигурацию агента из agents/<name>.jsonc."""
    path = os.path.join(AGENTS_DIR, f"{agent_name}.jsonc")
    with open(path, "r", encoding="utf-8") as f:
        return json5.loads(f.read())


def load_crew_config() -> dict:
    """Загружает конфигурацию crew из crew.jsonc."""
    with open(CREW_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json5.loads(f.read())


def build_agent(config: dict) -> Agent:
    """Создаёт CrewAI-агента по конфигу (tools, role, goal, backstory)."""
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


def cmd_collect(n: int, no_cache: bool = False) -> None:
    """Собирает n новых вакансий без использования агентов."""
    from src.collectors.pipeline import collect

    added, errors, attempts = collect(
        n_vacancies=n,
        query=QUERY,
        llm=get_llm(),
        use_cache=not no_cache,
    )
    print(f"\nСобрано: {added}, ошибок: {errors}, попыток: {attempts}")


def cmd_report() -> None:
    """Запускает Crew с writer-агентом и сохраняет отчёт в outputs/."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    crew_config = load_crew_config()

    agents = {
        name: build_agent(load_agent_config(name)) for name in crew_config["agents"]
    }

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

    logger.info(f"Usage metrics: {crew.usage_metrics}")

    saved_files = []
    for i, task in enumerate(tasks):
        if not task.output:
            logger.warning(f"Task {i + 1} returned no output")
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
        logger.info(f"Saved: {filepath}")

    print("\n" + "=" * 60)
    if saved_files:
        print("Сохранённые файлы:")
        for f in saved_files:
            print(f" - {f}")
    else:
        print("Ни один файл не был сохранён")
    print("=" * 60)
    print(result)


def cmd_all(n: int, no_cache: bool = False) -> None:
    """Сбор вакансий + генерация отчёта."""
    cmd_collect(n, no_cache=no_cache)
    cmd_report()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Collector & Reporter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Собрать вакансии в БД")
    p_collect.add_argument("--n", type=int, default=10, help="Сколько новых вакансий")
    p_collect.add_argument(
        "--no-cache", action="store_true", help="Игнорировать кэш поиска"
    )

    sub.add_parser("report", help="Сгенерировать отчёт по данным из БД")

    p_all = sub.add_parser("all", help="Сбор + отчёт")
    p_all.add_argument("--n", type=int, default=10)
    p_all.add_argument("--no-cache", action="store_true")

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args.n, no_cache=args.no_cache)
    elif args.command == "report":
        cmd_report()
    elif args.command == "all":
        cmd_all(args.n, no_cache=args.no_cache)


if __name__ == "__main__":
    main()
