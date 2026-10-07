# AGENTS.md

## Project overview

Коллектор вакансий hh.ru, аналитика через локальную LLM и подбор под резюме.
Python 3.10–3.13, PostgreSQL 18 + pgvector, CrewAI, LM Studio.
Подробные команды, настройки и схема описаны в `README.md`; используй его
для изменений соответствующего сценария, а не перечитывай весь проект
перед каждой небольшой правкой.

## Setup and checks

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env  # только при первоначальной настройке
```

Ruff закреплён в `pyproject.toml`, длина строки 88:

```bash
ruff check .
ruff format . --check
```

`ruff format .` изменяет файлы; запускай его только в рамках разрешённых правок.
Для Markdown-правок достаточно проверки diff, без подключения к сервисам.

Статическая проверка импорта хранилища, без подключения к БД:

```bash
python -c "from src.storage import VacancyStorage"
```

При изменениях хранилища можно проверить настроенную локальную БД:

```bash
python -c "from src.storage import VacancyStorage; VacancyStorage().close()"
```

Это подключение к PostgreSQL и выполнение DDL, а не проверка только импортов.
Не запускай его на неподтверждённом окружении или после несвязанных правок.

## Architecture and public interfaces

- `src/collectors/`: HHClient, SerperClient, scraper, extractor, pipeline.
- `src/analytics/`: VacancyExtractor, ResumeExtractor, stats, skills_keywords;
  `_extraction_utils.py` содержит общую очистку ответов LLM.
- `src/storage/`: VacancyStorage и файловый SearchCache.
- `src/matching/`: QwenEmbedder, embedding_text, matcher, match_report, resume_parser.
- `src/tools/stats_tool.py`: CrewAI-инструмент GetStatsTool.
- `main.py`: CLI и запуск CrewAI writer.

Поток: collect → analyze → embed-vacancies → match.
Резюме: parse_resume → ResumeExtractor → embed_query → save_resume.
`all-hh` и `all-serper` выполняют сбор и отчёт рынка, без анализа и эмбеддингов.

При рефакторинге сохраняй публичные имена, параметры, defaults, результаты
и поведение, если пользователь явно не запросил изменение:

- CLI: `analyze`, `embed-vacancies`, `save-resume`, `match`, `collect-hh`,
  `collect-serper`, `report`, `all-hh`, `all-serper`; аргументы и справка.
- Все публичные методы VacancyStorage, включая `add_vacancy`, `add_vacancies`,
  `save_analysis`, `save_embedding`, `save_resume`, `get_analyzed_ids`,
  `get_unanalyzed`, `get_unembedded`, `get_resume`, `find_top_vacancies`,
  `get_all`, `get_by_name`, `get_by_url`, `get_by_date`, `exists`, `count`,
  `close`, `__enter__`, `__exit__`; реэкспорт из `src.storage`.
- Функции `build_match_report`, `build_vacancy_text`, `build_resume_text`,
  `match_resume`, `parse_resume` и остальные публичные функции модулей.
- Классы VacancyExtractor, ResumeExtractor, QwenEmbedder и их публичные методы.

Не вводи mixin, абстрактные классы, Protocol или общий pipeline без конкретной
необходимости. Парсеры зарплат имеют разную семантику; не объединяй их механически.

## Code style and error handling

- Type hints для всех функций и методов, Google-style docstrings.
- `logging`, а не `print`; `print` допустим в CLI и ручных debug-скриптах.
- Ленивое форматирование логов: `logger.info("... %s", value)`.
- Не используй bare `except`. Предпочитай конкретные исключения.
- `except Exception` допустим для rollback с повторным выбрасыванием и для
  существующих границ обработки отдельной записи. Не сужай эти обработчики
  без проверки влияния на поведение; объясняй точечные подавления Ruff.
- Методы записи в БД выполняют commit на запись; при ошибке операции — rollback
  и повторное выбрасывание исключения. Не переноси транзакции между слоями
  и не добавляй повторные попытки без явной задачи.
- Локальные импорты допустимы для циклов и отложенной загрузки зависимости:
  HHClient импортируется внутри `collect_hh`, чтобы Serper не требовал HH cookies.

## LLM and embeddings

- Настройки и defaults определены кодом и `.env.example`.
  `LLM_MODEL_EXTRACTOR` выбирает extractor-модель, например gpt-oss-20b;
  при отсутствии используется `LLM_MODEL`.
- `LLM_MODEL` — writer и извлечение при сборе Serper, обычно ornith-1.0-9b-mlx.
- Эмбеддер: text-embedding-qwen3-embedding-4b, размерность 2560.
- `embed_document` — вакансии без инструкции; `embed_query` — резюме с инструкцией
  `Given a resume, retrieve relevant job vacancies`.
- Embedding-тексты вакансии и резюме симметричны: подписи, порядок полей,
  пустые значения и разделители нельзя менять только с одной стороны.
  Изменение текста требует плана пересчёта затронутых эмбеддингов.
- В llm_extractor и resume_extractor сохраняй JSON-схему промптов: ключи и типы.
  При изменении промпта повышай соответствующий `PROMPT_VERSION`.
- gpt-oss-20b — reasoning-модель, около трёх минут на вакансию.
  Для проверок используй `python main.py analyze --n 1`; не запускай обработку
  всей большой выборки без явного запроса пользователя.

## Database and output invariants

- Таблицы: `vacancies`, `vacancy_analysis`, `resumes`.
  Точная схема — в `VacancyStorage._create_table`.
- Конструктор создаёт недостающие таблицы, расширение vector и индексы.
  `CREATE TABLE IF NOT EXISTS` не обновляет существующую схему.
- Автоматических миграций нет. Изменение схемы требует обновления `_create_table`
  и отдельного плана обновления существующей БД с сохранением данных.
  Не используй `DROP TABLE` или пересоздание БД как стандартный способ миграции;
  разрушительные операции требуют прямого запроса пользователя.
- `stack`, `tasks`, `certifications`, `domains`, `programming_languages` — TEXT[].
  `vacancies.key_skills` — строка через запятую; это другое представление.
- Векторы — `vector(2560)`; не меняй размерность без плана пересчёта всех векторов.
- Не регистрируй общий адаптер Python list: он ломает TEXT[].
  Вектор сериализуется строкой `[v1,v2,...]` и передаётся через `%s::vector`.
- psycopg2 возвращает vector строкой; преобразование — через `_parse_vector`.
- Счётчик сохранённых эмбеддингов учитывает результат `save_embedding`.
- `cmd_match` сохраняет один полный Markdown-отчёт после вывода вакансий,
  включая пустой результат. Каталог outputs создаётся при записи отчёта.

## Testing and workflow

- `tests/debug_*.py` — ручные проверки; они могут обращаться к БД, LLM,
  внешним API и записывать файлы. Не запускай их все автоматически.
- Сейчас pytest-тестов нет. При их появлении запускай подходящие к изменению
  тесты; новые тесты размещай в `tests/test_*.py`, учитывая ограничения задачи.
- В первую очередь проверяй чистые функции очистки, валидации, зарплат,
  embedding-текстов и пересечений. Для исправлений проверяй ошибку и восстановление,
  а для CLI — параметры, счётчики и записанные отчёты.
- Не удаляй debug-скрипты без явного запроса.
- Не меняй `.env` и не выводи секреты; для примеров используй `.env.example`.
- `data/`, `outputs/`, `tests/data/` не добавляй в Git.
- `crew.jsonc`, `agents/*.jsonc` изменяй только по явному запросу.
- Оставляй изменения в рабочем дереве для ревью. Commit, merge, push, теги
  и публикация релиза — только по прямому запросу пользователя.
- Уточняй неоднозначные требования, влияющие на поведение или данные.
  Обычные решения по реализации принимай самостоятельно в рамках задачи.
- В результате укажи изменения, выполненные проверки и непроверенные сценарии.
