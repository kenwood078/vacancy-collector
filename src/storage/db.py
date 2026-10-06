import logging
import os
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
load_dotenv()


class VacancyStorage:
    """Хранилище вакансий в PostgreSQL с контекстным менеджером."""

    def __init__(self) -> None:
        """Открывает соединение с БД и создаёт таблицу vacancies, если её нет."""
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )
        self.conn.autocommit = False
        self._create_table()

    def _create_table(self) -> None:
        """Создаёт таблицы vacancies, vacancy_analysis, resumes если их нет."""
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vacancies (
                    -- Идентификация
                    id                      SERIAL PRIMARY KEY,
                    url                     TEXT UNIQUE NOT NULL,

                    -- Основное
                    name                    TEXT NOT NULL,
                    city                    VARCHAR(100),

                    -- Работодатель
                    employer                VARCHAR(200) NOT NULL,
                    employer_id             INTEGER,
                    employer_rating         NUMERIC(3,1),
                    employer_reviews_count  INTEGER,

                    -- Зарплата
                    salary                  TEXT,
                    salary_from             INTEGER,
                    salary_to               INTEGER,
                    salary_currency         VARCHAR(10),
                    salary_gross            BOOLEAN,

                    -- Контент
                    requirements            TEXT,
                    key_skills              TEXT,

                    -- Классификация
                    experience              VARCHAR(50),
                    work_format             TEXT,
                    employment_form         VARCHAR(50),
                    schedule                VARCHAR(50),
                    professional_role       INTEGER,

                    -- Метаданные публикации
                    published_at            TEXT,
                    responses_count         INTEGER,

                    -- Наши метаданные
                    collected_at            TEXT NOT NULL
                );
            """)
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vacancy_analysis (
                    vacancy_id            INTEGER PRIMARY KEY
                                          REFERENCES vacancies(id) ON DELETE CASCADE,

                    stack                 TEXT[],
                    tasks                 TEXT[],
                    certifications        TEXT[],
                    domains               TEXT[],
                    programming_languages TEXT[],
                    english_level         VARCHAR(20),

                    llm_model             VARCHAR(100),
                    prompt_version        VARCHAR(20),
                    analyzed_at           TEXT NOT NULL,

                    embedding_text        TEXT,
                    embedding             vector(2560),
                    embedding_model       VARCHAR(100),
                    embedded_at           TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS resumes (
                    id                    SERIAL PRIMARY KEY,
                    title                 VARCHAR(200),
                    role                  VARCHAR(200),
                    source_text           TEXT NOT NULL,

                    city                  VARCHAR(100),
                    work_format           VARCHAR(50),
                    experience_years      INTEGER,
                    salary_expectation    TEXT,
                    salary_min            INTEGER,
                    salary_max            INTEGER,
                    ready_to_relocate     BOOLEAN DEFAULT FALSE,

                    stack                 TEXT[],
                    tasks                 TEXT[],
                    certifications        TEXT[],
                    domains               TEXT[],
                    programming_languages TEXT[],
                    english_level         VARCHAR(20),

                    llm_model             VARCHAR(100),
                    prompt_version        VARCHAR(20),
                    created_at            TEXT NOT NULL,

                    embedding_text        TEXT,
                    embedding             vector(2560),
                    embedding_model       VARCHAR(100),
                    embedded_at           TEXT
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_employer_id ON vacancies(employer_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_collected_at ON vacancies(collected_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_experience ON vacancies(experience)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_professional_role ON vacancies(professional_role)"
            )
            self.conn.commit()

    def add_vacancy(self, vacancy: dict) -> bool:
        """
        Добавляет одну вакансию в БД.

        Args:
            vacancy: словарь с обязательными полями url, name, employer
                     и опциональными city, salary и т.д.

        Returns:
            True, если запись добавлена; False, если URL уже существует.

        Raises:
            ValueError: если отсутствует или пустое одно из обязательных полей.
        """
        required = ["url", "name", "employer"]
        for field in required:
            if not vacancy.get(field):
                raise ValueError(f"Field '{field}' is required and cannot be empty")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vacancies (
                    url, name, city,
                    employer, employer_id, employer_rating, employer_reviews_count,
                    salary, salary_from, salary_to, salary_currency, salary_gross,
                    requirements, key_skills,
                    experience, work_format, employment_form, schedule, professional_role,
                    published_at, responses_count,
                    collected_at
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s
                )
                ON CONFLICT (url) DO NOTHING
                """,
                (
                    vacancy["url"],
                    vacancy["name"],
                    vacancy.get("city"),
                    vacancy["employer"],
                    vacancy.get("employer_id"),
                    vacancy.get("employer_rating"),
                    vacancy.get("employer_reviews_count"),
                    vacancy.get("salary"),
                    vacancy.get("salary_from"),
                    vacancy.get("salary_to"),
                    vacancy.get("salary_currency"),
                    vacancy.get("salary_gross"),
                    vacancy.get("requirements"),
                    vacancy.get("key_skills"),
                    vacancy.get("experience"),
                    vacancy.get("work_format"),
                    vacancy.get("employment_form"),
                    vacancy.get("schedule"),
                    vacancy.get("professional_role"),
                    vacancy.get("published_at"),
                    vacancy.get("responses_count"),
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def save_analysis(self, analysis: dict) -> bool:
        """
        Upsert анализа вакансии в vacancy_analysis.

        Args:
            analysis: словарь от VacancyExtractor.extract() с полями
                vacancy_id, stack, tasks, certifications, domains,
                programming_languages, english_level, llm_model,
                prompt_version.

        Returns:
            True, если запись вставлена или обновлена.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vacancy_analysis (
                    vacancy_id,
                    stack, tasks, certifications, domains,
                    programming_languages, english_level,
                    llm_model, prompt_version, analyzed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (vacancy_id) DO UPDATE SET
                    stack = EXCLUDED.stack,
                    tasks = EXCLUDED.tasks,
                    certifications = EXCLUDED.certifications,
                    domains = EXCLUDED.domains,
                    programming_languages = EXCLUDED.programming_languages,
                    english_level = EXCLUDED.english_level,
                    llm_model = EXCLUDED.llm_model,
                    prompt_version = EXCLUDED.prompt_version,
                    analyzed_at = EXCLUDED.analyzed_at
                """,
                (
                    analysis["vacancy_id"],
                    analysis["stack"],
                    analysis["tasks"],
                    analysis["certifications"],
                    analysis["domains"],
                    analysis["programming_languages"],
                    analysis["english_level"],
                    analysis["llm_model"],
                    analysis["prompt_version"],
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def get_analyzed_ids(self) -> set[int]:
        """Возвращает set vacancy_id, для которых уже есть анализ."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT vacancy_id FROM vacancy_analysis")
            return {row[0] for row in cur.fetchall()}

    def get_unanalyzed(self, limit: int | None = None) -> list[dict]:
        """
        Возвращает вакансии, для которых ещё нет записи в vacancy_analysis.

        Args:
            limit: максимум записей. None — все.

        Returns:
            Список словарей из vacancies.
        """
        query = """
            SELECT v.* FROM vacancies v
            LEFT JOIN vacancy_analysis a ON a.vacancy_id = v.id
            WHERE a.vacancy_id IS NULL
            ORDER BY v.id DESC
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            if limit is not None:
                cur.execute(query + " LIMIT %s", (limit,))
            else:
                cur.execute(query)
            return cur.fetchall()

    def save_embedding(
        self,
        vacancy_id: int,
        embedding_text: str,
        embedding: list[float],
        model: str,
    ) -> bool:
        """
        Сохраняет эмбеддинг вакансии в vacancy_analysis.

        Args:
            vacancy_id: ID вакансии.
            embedding_text: текст, из которого считался вектор.
            embedding: список float длиной 2560.
            model: имя модели эмбеддинга.

        Returns:
            True, если запись обновлена.
        """
        # pgvector принимает вектор строкой '[v1,v2,...]'
        vec_str = "[" + ",".join(map(str, embedding)) + "]"

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE vacancy_analysis
                    SET embedding_text = %s,
                        embedding = %s::vector,
                        embedding_model = %s,
                        embedded_at = %s
                    WHERE vacancy_id = %s
                    """,
                    (
                        embedding_text,
                        vec_str,
                        model,
                        datetime.now().isoformat(),
                        vacancy_id,
                    ),
                )
                self.conn.commit()
                return cur.rowcount > 0
        except Exception:
            self.conn.rollback()
            raise

    def get_unembedded(self, limit: int | None = None) -> list[dict]:
        """
        Возвращает vacancy_analysis с JOIN vacancies, где ещё нет эмбеддинга.

        Args:
            limit: максимум записей. None — все.

        Returns:
            Список словарей с полями вакансии и анализа.
        """
        query = """
            SELECT
                v.id, v.name, v.key_skills, v.requirements,
                a.vacancy_id, a.stack, a.tasks, a.certifications,
                a.domains, a.programming_languages, a.english_level
            FROM vacancy_analysis a
            JOIN vacancies v ON v.id = a.vacancy_id
            WHERE a.embedding IS NULL
            ORDER BY v.id DESC
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            if limit is not None:
                cur.execute(query + " LIMIT %s", (limit,))
            else:
                cur.execute(query)
            return cur.fetchall()

    def save_resume(
        self,
        title: str,
        source_text: str,
        analysis: dict,
        embedding_text: str,
        embedding: list[float],
        model: str,
    ) -> int:
        """Сохраняет резюме с анализом и эмбеддингом. Возвращает id."""
        vec_str = "[" + ",".join(map(str, embedding)) + "]"
        now = datetime.now().isoformat()

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resumes (
                        title, role, source_text,
                        city, work_format, experience_years,
                        salary_expectation, salary_min, salary_max, ready_to_relocate,
                        stack, tasks, certifications, domains,
                        programming_languages, english_level,
                        llm_model, prompt_version, created_at,
                        embedding_text, embedding, embedding_model, embedded_at
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s::vector, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        title,
                        analysis["role"],
                        source_text,
                        analysis["city"],
                        analysis["work_format"],
                        analysis["experience_years"],
                        analysis["salary_expectation"],
                        analysis["salary_min"],
                        analysis["salary_max"],
                        analysis["ready_to_relocate"],
                        analysis["stack"],
                        analysis["tasks"],
                        analysis["certifications"],
                        analysis["domains"],
                        analysis["programming_languages"],
                        analysis["english_level"],
                        analysis["llm_model"],
                        analysis["prompt_version"],
                        now,
                        embedding_text,
                        vec_str,
                        model,
                        now,
                    ),
                )
                resume_id = cur.fetchone()[0]
                self.conn.commit()
                return resume_id
        except Exception:
            self.conn.rollback()
            raise

    def get_resume(self, resume_id: int) -> dict | None:
        """Возвращает резюме по id или None."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM resumes WHERE id = %s", (resume_id,))
            return cur.fetchone()

    def find_top_vacancies(
        self,
        embedding: list[float],
        resume: dict,
        top_n: int = 20,
    ) -> list[dict]:
        """
        Векторный поиск top-N вакансий с жёсткими фильтрами по резюме.

        Фильтры применяются мягко: если данных для фильтра нет — он пропускается.

        Args:
            embedding: вектор резюме.
            resume: строка из таблицы resumes.
            top_n: сколько вакансий вернуть.

        Returns:
            Список словарей с полями вакансии + score.
        """
        vec_str = "[" + ",".join(map(str, embedding)) + "]"
        where = ["a.embedding IS NOT NULL"]
        params: list = []

        # 1. Опыт
        years = resume.get("experience_years")
        allowed = self._allowed_experience(years)
        if allowed:
            where.append("v.experience = ANY(%s)")
            params.append(allowed)

        # 2. Зарплата: отсеиваем только явные провалы
        salary_min = resume.get("salary_min")
        if salary_min:
            where.append("(v.salary_to IS NULL OR v.salary_to >= %s)")
            params.append(salary_min)

        # 3. Город: если не готов к переезду — требуем совпадения или REMOTE
        if not resume.get("ready_to_relocate"):
            city = resume.get("city")
            if city and city != "unknown":
                where.append("(v.city = %s OR v.work_format ILIKE '%%REMOTE%%')")
                params.append(city)

        where_sql = " AND ".join(where)

        query = f"""
            SELECT
                v.id, v.name, v.employer, v.city, v.salary,
                v.experience, v.work_format, v.url,
                a.stack, a.tasks, a.certifications, a.domains,
                a.programming_languages, a.english_level,
                ROUND((1 - (a.embedding <=> %s::vector))::numeric, 4) AS score
            FROM vacancy_analysis a
            JOIN vacancies v ON v.id = a.vacancy_id
            WHERE {where_sql}
            ORDER BY a.embedding <=> %s::vector
            LIMIT %s
        """
        full_params = [vec_str, *params, vec_str, top_n]

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, full_params)
            return cur.fetchall()

    @staticmethod
    def _allowed_experience(years: int | None) -> list[str] | None:
        """
        Маппит годы опыта в допустимые значения hh.ru enum.

        Args:
            years: число лет опыта из резюме.

        Returns:
            Список допустимых значений или None (не фильтровать).
        """
        if years is None:
            return None
        if years < 3:
            return ["noExperience", "between1And3"]
        if years < 6:
            return ["between1And3", "between3And6"]
        return ["between3And6", "moreThan6"]

    def add_vacancies(self, vacancies: list[dict]) -> tuple[int, int, int]:
        """
        Добавляет список вакансий.

        Returns:
            Кортеж (добавлено, ошибок, всего).
        """
        added = errors = 0
        for vacancy in vacancies:
            try:
                if self.add_vacancy(vacancy):
                    added += 1
                else:
                    logger.info(f"Duplicate: {vacancy.get('url')}")
            except Exception as e:
                logger.error(f"Failed to add {vacancy.get('name')}: {e}")
                errors += 1
        return added, errors, len(vacancies)

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[dict]:
        """Возвращает вакансии (сортировка по id DESC) с пагинацией."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM vacancies ORDER BY id DESC"
            if limit is not None:
                query += " LIMIT %s OFFSET %s"
                cur.execute(query, (limit, offset))
            else:
                cur.execute(query)
            return cur.fetchall()

    def get_by_name(self, patterns: list[str], limit: int | None = None) -> list[dict]:
        """
        Возвращает вакансии, у которых в name встречается любой из patterns
        (регистронезависимо, ILIKE).

        Args:
            patterns: список подстрок, например ["Сет", "Net"].
            limit: максимум записей.

        Returns:
            Список словарей.
        """
        if not patterns:
            return []

        conditions = " OR ".join(["name ILIKE %s"] * len(patterns))
        params = [f"%{p}%" for p in patterns]

        query = f"SELECT * FROM vacancies WHERE {conditions} ORDER BY id DESC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_by_url(self, url: str) -> dict | None:
        """Возвращает вакансию по URL или None."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM vacancies WHERE url = %s", (url,))
            return cur.fetchone()

    def get_by_date(self, start_date: str, end_date: str) -> list[dict]:
        """
        Возвращает вакансии за диапазон дат collected_at (ISO-8601).

        Если end_date передана как 'YYYY-MM-DD' (10 символов), расширяется
        до конца дня.
        """
        if len(end_date) == 10:
            end_date += "T23:59:59.999999"
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM vacancies WHERE collected_at BETWEEN %s AND %s",
                (start_date, end_date),
            )
            return cur.fetchall()

    def count(self) -> int:
        """Возвращает общее количество записей."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM vacancies")
            return cur.fetchone()[0]

    def exists(self, url: str) -> bool:
        """Проверяет, есть ли вакансия с данным URL в БД."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM vacancies WHERE url = %s)", (url,))
            return cur.fetchone()[0]

    def close(self) -> None:
        """Закрывает соединение с БД, если оно открыто."""
        if self.conn and not self.conn.closed:
            self.conn.close()

    def __enter__(self) -> "VacancyStorage":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
