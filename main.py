import argparse
import logging
import os
from datetime import datetime

import json5
from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv

from src.tools.stats_tool import GetStatsTool

# Импортируем .env
load_dotenv()
# SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# Определяем константы
BASE_DIR = os.path.dirname(__file__)
AGENTS_DIR = os.path.join(BASE_DIR, "agents")
CREW_CONFIG_PATH = os.path.join(BASE_DIR, "crew.jsonc")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.environ["OPENAI_API_KEY"] = "not-needed"
# print(f"BASE_DIR = {BASE_DIR}")
# print(f"OUTPUTS_DIR = {OUTPUTS_DIR}")

QUERY = """
site:hh.ru/vacancy (intitle:"Network Engineer" OR intitle:"Сетевой инженер" OR intitle:"Network Architect" OR intitle:"Сетевой архитектор" OR intitle:"Сетевой администратор") (Москва OR "Санкт-Петербург") (удаленно OR удалённо OR remote OR дистанционно OR "удаленная работа") -архив -архиве -стажер -стажёр -junior -помощник -техподдержка -support
"""


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def get_llm() -> LLM:
    return LLM(
        model="ornith-1.0-9b-mlx@8bit",
        base_url="http://localhost:1234/v1",
        api_key="not-needed",
        temperature=0.6,
    )


def cmd_collect(n: int):
    from src.collectors.pipeline import collect

    llm = get_llm()
    added, errors, attempts = collect(n_vacancies=n, query=QUERY, llm=llm)
    print(f"\nСобрано: {added}, ошибок: {errors}, попыток: {attempts}")


def cmd_all(n: int):
    cmd_collect(n)
    cmd_report()


# --- Инструменты ---
AVAILABLE_TOOLS = {
    "GetStatsTool": GetStatsTool(),
}


def load_agent_config(agent_name: str) -> dict:
    """Загружает конфигурацию агента с использованием json5"""
    path = os.path.join(AGENTS_DIR, f"{agent_name}.jsonc")
    with open(path, "r", encoding="utf-8") as f:
        return json5.loads(f.read())


def load_crew_config() -> dict:
    """Загружает конфигурацию crew с использованием json5"""
    with open(CREW_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json5.loads(f.read())


def build_agent(agent_name: str, config: dict) -> Agent:
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


def cmd_report():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    crew_config = load_crew_config()
    agent_names = crew_config["agents"]

    # 1. Создаём агентов
    agents = {}
    for name in agent_names:
        config = load_agent_config(name)
        agents[name] = build_agent(name, config)

    # 2. Создаём задачи (без output_file, будем сохранять вручную)
    tasks = []
    task_dict = {}
    for task_conf in crew_config["tasks"]:
        agent = agents[task_conf["agent"]]
        markdown = task_conf.get("markdown", False)
        task = Task(
            description=task_conf["description"],
            expected_output=task_conf["expected_output"],
            agent=agent,
            markdown=markdown,
        )
        tasks.append(task)
        task_dict[task_conf["name"]] = task

    # 3. Подставляем контекст
    for i, task_conf in enumerate(crew_config["tasks"]):
        if "context" in task_conf:
            tasks[i].context = [
                task_dict[name] for name in task_conf["context"] if name in task_dict
            ]
        elif i > 0:
            tasks[i].context = [tasks[i - 1]]

    # 4. Создаём Crew и запускаем
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

    print("🚀 Запуск поиска вакансий и аналитики...\n")
    result = crew.kickoff()
    print("=" * 60)
    print("USAGE METRICS:")
    print(crew.usage_metrics)
    print("=" * 60)

    # 5. Сохраняем вывод каждой задачи вручную
    saved_files = []
    for i, task in enumerate(tasks):
        if task.output:
            task_name = crew_config["tasks"][i]["name"]
            if task_name == "analysis_task":
                filename = f"report_{timestamp}.md"
            else:
                filename = f"task_{i}_{timestamp}.txt"
            filepath = os.path.join(OUTPUTS_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(task.output.raw)
            saved_files.append(filepath)
            print(f"💾 Сохранён вывод задачи {i + 1} в {filepath}")
        else:
            print(f"⚠️ Задача {i + 1} не вернула output.")

    # 6. Вывод сохранённых файлов
    if saved_files:
        print("\n" + "=" * 60)
        print("✅ РАБОТА ЗАВЕРШЕНА. СОХРАНЁННЫЕ ФАЙЛЫ:")
        for f in saved_files:
            print(f" - {f}")
        print("=" * 60)
    else:
        print("\n⚠️ Ни один файл не был сохранён (задачи не вернули output).")

    print("\n" + "=" * 60)
    print("📄 ИТОГОВЫЙ ОТЧЁТ (финальный результат Crew):")
    print("=" * 60)
    print(result)


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Collector & Reporter")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("collect")
    p1.add_argument("--n", type=int, default=10)

    sub.add_parser("report")

    p2 = sub.add_parser("all")
    p2.add_argument("--n", type=int, default=10)

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args.n)
    elif args.command == "report":
        cmd_report()
    elif args.command == "all":
        cmd_all(args.n)


if __name__ == "__main__":
    main()
