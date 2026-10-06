                                                             # AGENTS.md

## Project overview

Vacancy collector and analyst for hh.ru.
Collects vacancies, extracts structured fields via local LLM, stores in PostgreSQL
with pgvector embeddings, and matches resumes to vacancies by cosine similarity.

Python 3.10+, PostgreSQL 18 + pgvector, CrewAI, LM Studio (OpenAI-compatible).

## Commands

**Setup**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # заполнить DB_*, HH_*, SERPER_API_KEY, LLM_*
```

**Run**
```bash
python main.py collect-hh --n 50
python main.py analyze
python main.py embed-vacancies
python main.py save-resume --path data/resume.txt
python main.py match --resume-id 6
```

**Lint / format**
```bash
ruff check .
ruff format .
```

**Tests**
```bash
pytest
```

## Architecture

```
src/
├── collectors/     # hh_client, serper, scraper, extractor, pipeline
├── analytics/      # llm_extractor (вакансии), resume_extractor (резюме), stats
├── storage/        # db.py (VacancyStorage), cache.py
├── matching/       # embedder, embedding_text, matcher, match_report, resume_parser
└── tools/          # stats_tool (CrewAI)
```

Data flow: collect → analyze (LLM) → embed (Qwen3-Embedding-4B) → match.

DB schema: `vacancies` (raw), `vacancy_analysis` (structured + embedding),
`resumes` (structured + embedding). Embeddings — `vector(2560)`.

## Code style

- Ruff for lint and format. Line length 88.
- Type hints on all functions, Google-style docstrings.
- `logging` module, not `print` (кроме CLI-вывода).
- f-strings, but `logger.info("... %s", x)` for lazy formatting.
- No bare `except`. Specific exception types.

## LLM / embedding

- Extractor: `gpt-oss-20b` via LM Studio (`LLM_MODEL_EXTRACTOR`).
- Writer: `ornith-1.0-9b-mlx` (`LLM_MODEL`).
- Embedder: `text-embedding-qwen3-embedding-4b`, dim 2560.
- `embed_document` (без инструкции) — для вакансий.
- `embed_query` (с `Instruct: Given a resume, ...`) — для резюме.
- Промпты: `PROMPT_VERSION` в `llm_extractor.py` и `resume_extractor.py`.
  При изменении промпта — поднимать версию.

## Testing

- `tests/` — debug-скрипты для ручной проверки (`debug_*.py`), не pytest.
- При рефакторинге не удалять debug-скрипты без явного запроса.
- Новые тесты — pytest, в `tests/test_*.py`.
- Чистые функции (`_clean`, `_validate`, `_parse_salary`, `_stack_overlap`) —
  покрывать в первую очередь.

## Database

- PostgreSQL 18 + pgvector. Расширение `vector` должно быть установлено.
- Миграции не автоматические. Схема создаётся в `VacancyStorage._create_table`
  через `CREATE TABLE IF NOT EXISTS`.
- При изменении схемы — обновлять `_create_table` и вручную пересоздавать
  таблицу (`DROP TABLE ...`).
- `TEXT[]` для списков (stack, tasks, domains). Не менять на `TEXT` через запятую.
- `embedding vector(2560)` — размерность Qwen3-Embedding-4B. Не менять без
  пересчёта всех эмбеддингов.

## Boundaries — do not touch

- `.env` — не редактировать, не коммитить. Только `.env.example`.
- `data/`, `outputs/` — в `.gitignore`. Не добавлять в git.
- `crew.jsonc`, `agents/*.jsonc` — рабочий конфиг CrewAI. Менять только
  по явному запросу.
- `db.py` — при рефакторинге сохранять публичные имена методов:
  `save_analysis`, `save_embedding`, `save_resume`, `find_top_vacancies`,
  `get_unanalyzed`, `get_unembedded`, `get_resume`.
- Промпты в `llm_extractor` / `resume_extractor` — при изменении
  сохранять структуру JSON-ответа (ключи, типы).

## Workflow for refactoring

1. Прочитай `AGENTS.md` и `README.md`.
2. Не меняй публичные сигнатуры функций без явного запроса.
3. После изменений — `ruff check .` и
   `python -c "from src.storage import VacancyStorage; VacancyStorage().close()"`
   для проверки импортов.
4. Не коммить. Оставить изменения в рабочем дереве для ревью.
5. Если что-то неясно — спросить, не догадываться.

## Gotchas

- `register_adapter(list, ...)` в `db.py` нельзя возвращать — он ломает
  `TEXT[]`-поля. Вектор передаётся строкой `'[v1,v2,...]'::vector`.
- `psycopg2` возвращает `vector` как строку. Парсить через `_parse_vector`.
- `embedding_text` симметричен для вакансии и резюме. Порядок полей
  фиксирован. Не менять порядок только в одной функции.
- `gpt-oss-20b` — reasoning-модель, ~3 минуты на вакансию. Не запускать
  `analyze` без `--n` на больших выборках без предупреждения.