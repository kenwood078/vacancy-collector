# Vacancy Collector

Инструмент для сбора и анализа вакансий с hh.ru. Собирает данные через Serper (Google Search),
извлекает структурированные поля локальной LLM, хранит в PostgreSQL и генерирует
аналитический отчёт через CrewAI.

## Возможности

- Поиск вакансий через Serper + Google
- Извлечение полей локальной LLM (изолированные вызовы, ~4.5k токенов на вакансию)
- PostgreSQL с дедупликацией по URL
- Аналитика без LLM: топ-навыки, зарплаты, города, компании
- Markdown-отчёт через CrewAI-агента (writer)
- Кэш поиска с TTL
- CLI: `collect` / `report` / `all`

## Требования

- Python 3.10+
- PostgreSQL
- LM Studio (или OpenAI-совместимый сервер)
- [Serper API](https://serper.dev)

## Установка

```bash
git clone https://github.com/kenwood078/vacancy-collector
cd vacancy-collector
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Настройка

```bash
cp .env.example .env
# заполнить значения
```

## Использование

```bash
python main.py collect --n 10            # собрать 10 новых
python main.py collect --n 10 --no-cache # без кэша
python main.py report                    # только отчёт
python main.py all --n 10                # сбор + отчёт
```

Отчёты сохраняются в `outputs/report_<timestamp>.md`.

## Структура

```
src/
├── collectors/       # serper, scraper, extractor, pipeline
├── storage/          # db (PostgreSQL), cache
├── analytics/        # stats, skills_keywords
└── tools/            # stats_tool (для CrewAI)
tests/                # debug-скрипты
agents/               # конфиги CrewAI
data/                 # кэш
outputs/              # отчёты
```

## Архитектура

```
Serper → URLs → scrape → LLM extract → PostgreSQL
                                            ↓
                                    compute_statistics()
                                            ↓
                                      CrewAI writer
                                            ↓
                                     Markdown report
```

## Статус

- **v1.0-serper** — стабильный релиз (Serper + Google)
- **feature/hh-direct** — прямой сбор с hh.ru (в разработке)

## Лицензия

MIT