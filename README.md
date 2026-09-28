# Vacancy Collector

Сбор вакансий с hh.ru и аналитика рынка через локальную LLM.
Два источника сбора: прямой через cookie-сессию hh.ru и через Serper (Google).

## Возможности

- **Прямой сбор с hh.ru** через cookie-сессию (`collect-hh`)
- **Fallback-сбор через Serper** (Google Search) (`collect-serper`)
- **PostgreSQL** — расширенная схема: опыт, формат работы, зарплата, метаданные публикации
- **Аналитика без LLM** — города, навыки, зарплаты, компании, опыт, формат работы
- **Markdown-отчёт** через CrewAI-агента (writer)
- **CLI** — 5 команд: collect-hh, collect-serper, report, all-hh, all-serper

## Требования

- Python 3.10+
- PostgreSQL
- LM Studio (или OpenAI-совместимый сервер)
- Cookies hh.ru (для `collect-hh`)
- Serper API ключ (для `collect-serper`)

## Установка

```bash
git clone <repo-url>
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

### Как получить cookies hh.ru

1. Открой hh.ru в браузере и залогинься.
2. DevTools (`⌥⌘I` в Safari) → **Application** → **Cookies** → `hh.ru`.
3. Скопируй значения `hhtoken` и `_xsrf` в `.env`:
   ```
   HH_TOKEN=...
   HH_XSRF=...
   ```
4. Cookies живут несколько недель. Если сбор перестал работать — обнови.

## Использование

```bash
# Прямой сбор с hh.ru
python main.py collect-hh --n 20

# Сбор через Serper
python main.py collect-serper --n 20

# Сгенерировать отчёт по данным из БД
python main.py report

# Полный цикл: сбор + отчёт
python main.py all-hh --n 20
python main.py all-serper --n 20
```

Отчёты сохраняются в `outputs/report_<timestamp>.md`.

## Структура

```
src/
├── collectors/         # Сбор данных
│   ├── hh_client.py    # HHClient: прямой сбор с hh.ru
│   ├── serper.py       # SerperClient: поиск через Google
│   ├── scraper.py      # Скрапинг страниц
│   ├── extractor.py    # Извлечение полей через LLM
│   └── pipeline.py     # collect_hh + collect_serper
├── storage/            # Хранение
│   ├── db.py           # PostgreSQL + схема vacancies
│   └── cache.py        # Файловый кэш поиска
├── analytics/          # Аналитика без LLM
│   ├── stats.py        # compute_statistics
│   └── skills_keywords.py
└── tools/              # CrewAI-инструменты
    └── stats_tool.py   # GetStatsTool для writer
tests/                  # debug-скрипты
agents/                 # конфиги CrewAI
crew.jsonc              # конфиг Crew
```

## Архитектура

### Сбор через hh.ru (основной)

```
HHClient.search() → список вакансий (100/страница)
    ↓
HHClient.fetch_full(vacancy) → detail + все поля
    ↓
VacancyStorage.add_vacancy() → PostgreSQL
```

### Сбор через Serper (альтернативный)

```
Serper → URLs → scrape → LLM extract → PostgreSQL
```

### Генерация отчёта

```
PostgreSQL → compute_statistics() → GetStatsTool → CrewAI writer → Markdown
```

## Схема БД

```sql
vacancies (
    id, url, employer_id,
    name, company, city, salary,
    requirements, key_skills,
    experience, work_format, employment_form,
    published_at, responses_count,
    collected_at
)
```

## Статус

- **v1.0-serper** — стабильный релиз (Serper + Google). Тег в git.
- **feature/hh-direct** — прямой сбор с hh.ru (текущая работа).