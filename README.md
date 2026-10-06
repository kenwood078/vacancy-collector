# Vacancy Collector

Сбор вакансий с hh.ru, анализ через локальную LLM и подбор вакансий под резюме.
Два источника сбора: cookie-сессия hh.ru и Google Search через Serper.

## Возможности

- Сбор вакансий напрямую с hh.ru или через Serper с файловым кэшем.
- Извлечение стека, задач, сертификатов, доменов и языков через LLM.
- Хранение вакансий, анализа и резюме в PostgreSQL с pgvector.
- Эмбеддинги Qwen3-Embedding-4B и поиск по косинусному расстоянию.
- Фильтрация подбора по опыту, зарплате и городу с учётом готовности к переезду.
- Статистика рынка без LLM и Markdown-отчёт через CrewAI writer.
- Девять CLI-команд для сбора, анализа, эмбеддингов, резюме и отчётов.

## Требования

- Python 3.10–3.13.
- PostgreSQL 18 с установленным расширением pgvector.
- LM Studio или OpenAI-совместимый сервер с моделями для генерации и эмбеддингов.
- Cookies hh.ru для `collect-hh` и `all-hh`.
- Ключ Serper API для `collect-serper` и `all-serper`; HH cookies для них не нужны.

## Установка

В каталоге проекта:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Для разработки, включая закреплённую версию Ruff:

```bash
pip install -e '.[dev]'
```

## Настройка

Заполните `.env` по образцу `.env.example`:

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — подключение к БД.
- `HH_TOKEN`, `HH_XSRF` — cookies для прямого сбора.
- `SERPER_API_KEY` — ключ поиска Serper.
- `USE_CACHE`, `CACHE_TTL_HOURS` — кэш Serper; TTL по умолчанию 24 часа,
  нулевое или отрицательное значение отключает истечение.
- `LLM_BASE_URL`, `LLM_API_KEY` — адрес и ключ OpenAI-совместимого сервера.
- `LLM_MODEL` — writer-модель; также используется при сборе через Serper.
- `LLM_MODEL_EXTRACTOR` — модель анализа вакансий и резюме, например `openai/gpt-oss-20b`.
  Если переменная не задана, используется `LLM_MODEL`.
- `EMBEDDING_MODEL` — модель эмбеддингов;
  по умолчанию `text-embedding-qwen3-embedding-4b`, размерность 2560.

Cookies можно взять из DevTools браузера: Application → Cookies → hh.ru.
Значения `hhtoken` и `_xsrf` перенесите в соответствующие переменные `.env`.
Если сессия перестала работать, обновите cookies.

## Команды

| Команда | Назначение | Аргументы |
|---|---|---|
| `collect-hh` | Прямой сбор | `--n`, по умолчанию 10 |
| `collect-serper` | Serper → scrape → LLM → БД | `--n`, по умолчанию 10; `--no-cache` |
| `analyze` | Структурированный анализ вакансий без анализа | `--n`; без аргумента — все |
| `embed-vacancies` | Эмбеддинги проанализированных вакансий без вектора | `--n`; без аргумента — все |
| `save-resume` | Чтение, анализ, эмбеддинг и сохранение резюме | обязательный `--path` |
| `match` | Подбор вакансий и Markdown-отчёт | обязательный `--resume-id`; `--top`, по умолчанию 20 |
| `report` | Отчёт о рынке через CrewAI writer | нет |
| `all-hh` | Прямой сбор, затем отчёт о рынке | `--n`, по умолчанию 10 |
| `all-serper` | Сбор Serper, затем отчёт о рынке | `--n`, по умолчанию 10; `--no-cache` |

Полный путь от сбора к подбору:

```bash
python main.py collect-hh --n 20
python main.py analyze --n 20
python main.py embed-vacancies --n 20
python main.py save-resume --path data/resume.txt
# Используйте resume_id, выведенный предыдущей командой.
python main.py match --resume-id 6 --top 20
```

`gpt-oss-20b` может обрабатывать одну вакансию около трёх минут.
Для пробного запуска задавайте `analyze --n`; без ограничения обрабатываются
все вакансии без анализа.

Альтернативный сбор и отчёт о рынке:

```bash
python main.py collect-serper --n 20 --no-cache
python main.py report
python main.py all-hh --n 20
python main.py all-serper --n 20
```

`all-hh` и `all-serper` выполняют сбор и отчёт о рынке;
анализ и эмбеддинги для матчинга запускаются отдельными командами.

Поддерживаемые форматы резюме: `.txt`, `.md`, `.text` в UTF-8.
Отчёты рынка сохраняются в `outputs/report_<timestamp>.md`,
отчёты подбора — в `outputs/match_resume_<id>_<timestamp>.md`.
Отчёт подбора создаётся один раз, включая случай без найденных вакансий.
Каталог `outputs/` создаётся при сохранении отчёта.

## Структура и поток данных

```text
main.py                  CLI и запуск CrewAI
src/
├── collectors/          HHClient, SerperClient, scrape, extract_vacancy, pipeline
├── analytics/           VacancyExtractor, ResumeExtractor, stats, skills_keywords
├── storage/             VacancyStorage и SearchCache
├── matching/            QwenEmbedder, embedding_text, matcher, match_report, resume_parser
└── tools/               GetStatsTool для writer
agents/                  конфиги агентов CrewAI
crew.jsonc               конфигурация CrewAI
tests/                   debug-скрипты для ручных проверок
```

```text
HH search → detail → vacancies
Serper → URLs → scrape → LLM extract → vacancies
vacancies → VacancyExtractor → vacancy_analysis → embed_document
резюме → parse_resume → ResumeExtractor → embed_query → resumes
resumes → SQL-фильтры + векторный поиск → Markdown-отчёт подбора
vacancies → compute_statistics → GetStatsTool → CrewAI writer → отчёт рынка
```

Embedding-тексты вакансии и резюме имеют одинаковые подписи и порядок полей.
Инструкция Qwen3 добавляется только к запросу резюме.

## База данных

`VacancyStorage` при создании соединения выполняет `CREATE TABLE IF NOT EXISTS`,
создание расширения `vector` и индексов. База должна существовать,
а пользователь — иметь права на эти операции. Автоматических миграций нет.

| Таблица | Основные поля |
|---|---|
| `vacancies` | `id`, уникальный `url`, `name`, `employer` и его метаданные, `city`, зарплата строкой и числовыми границами, `requirements`, `key_skills`, опыт, формат, занятость, график, роль, даты и число откликов |
| `vacancy_analysis` | `vacancy_id` → `vacancies.id`, структурированные списки, `english_level`, метаданные LLM и анализа, текст и вектор эмбеддинга, модель и дата эмбеддинга |
| `resumes` | `id`, `title`, `role`, `source_text`, город, формат, стаж, зарплатные ожидания и границы, готовность к переезду, структурированные списки, метаданные LLM и эмбеддинга |

В анализе и резюме `stack`, `tasks`, `certifications`, `domains`,
`programming_languages` имеют тип `TEXT[]`. Эмбеддинги — `vector(2560)`.
`vacancies.key_skills` хранит теги hh.ru строкой через запятую.
Точная схема находится в `VacancyStorage._create_table`.

## Проверки

```bash
ruff check .
ruff format . --check
```

Проверка подключения и инициализации хранилища выполняет DDL:

```bash
python -c "from src.storage import VacancyStorage; VacancyStorage().close()"
```

`tests/debug_*.py` — ручные проверки, а не pytest-тесты.
Они могут обращаться к БД, внешним сервисам и локальной LLM;
запускайте выбранный скрипт с нужными настройками.
Файлы `.env`, `data/` и `outputs/` не добавляются в Git.
