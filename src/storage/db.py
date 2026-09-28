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
        """Создаёт таблицу vacancies, если её нет."""
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vacancies (
                    -- Идентификация
                    id                SERIAL PRIMARY KEY,
                    url               TEXT UNIQUE NOT NULL,
                    employer_id       INTEGER,              -- ссылка на будущую таблицу companies
                
                    -- Основное
                    name              TEXT NOT NULL,
                    company           VARCHAR(200) NOT NULL,
                    city              VARCHAR(100),
                    salary            TEXT,
                
                    -- Контент
                    requirements      TEXT,
                    key_skills        TEXT,
                
                    -- Классификация
                    experience        VARCHAR(50),
                    work_format       TEXT,
                    employment_form   VARCHAR(50),
                
                    -- Метаданные публикации
                    published_at      TEXT,
                    responses_count   INTEGER,
                
                    -- Наши метаданные
                    collected_at      TEXT NOT NULL
                );
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
            self.conn.commit()

    def add_vacancy(self, vacancy: dict) -> bool:
        """
        Добавляет одну вакансию в БД.

        Args:
            vacancy: словарь с обязательными полями url, name, company
                     и опциональными city, salary, requirements,
                     experience, work_format, employment_form,
                     published_at, employer_id, responses_count, key_skills.

        Returns:
            True, если запись добавлена; False, если URL уже существует.

        Raises:
            ValueError: если отсутствует или пустое одно из обязательных полей.
        """
        required = ["url", "name", "company"]
        for field in required:
            if not vacancy.get(field):
                raise ValueError(f"Field '{field}' is required and cannot be empty")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vacancies (
                    url, name, company, city, salary, requirements,
                    experience, work_format, employment_form,
                    published_at, employer_id, responses_count, key_skills,
                    collected_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s
                )
                ON CONFLICT (url) DO NOTHING
                """,
                (
                    vacancy["url"],
                    vacancy["name"],
                    vacancy["company"],
                    vacancy.get("city"),
                    vacancy.get("salary"),
                    vacancy.get("requirements"),
                    vacancy.get("experience"),
                    vacancy.get("work_format"),
                    vacancy.get("employment_form"),
                    vacancy.get("published_at"),
                    vacancy.get("employer_id"),
                    vacancy.get("responses_count"),
                    vacancy.get("key_skills"),
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

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
