import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
load_dotenv()


class VacancyStorage:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )
        self.conn.autocommit = False
        self._create_table()

    def _create_table(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vacancies (
                    id SERIAL PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    company VARCHAR(100) NOT NULL,
                    city VARCHAR(100),
                    salary TEXT,
                    requirements TEXT,
                    collected_at TEXT
                )
            """)
            self.conn.commit()

    def add_vacancy(self, vacancy: dict) -> bool:
        """
        Добавляет одну вакансию.
        Возвращает True, если вставка выполнена, False — если URL уже существует.
        """
        # Проверяем обязательные поля
        required = ["url", "name", "company"]
        for field in required:
            if field not in vacancy:
                raise ValueError(f"Missing required field: {field}")

        # Валидация данных
        if (
            not vacancy.get("url")
            or not vacancy.get("name")
            or not vacancy.get("company")
        ):
            raise ValueError("url, name и company не могут быть пустыми")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vacancies (url, name, company, city, salary, requirements, collected_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
            """,
                (
                    vacancy["url"],
                    vacancy["name"],
                    vacancy["company"],
                    vacancy.get("city"),
                    vacancy.get("salary"),
                    vacancy.get("requirements"),
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0  # rowcount == 1 если вставлено, 0 если дубликат

    def add_vacancies(self, vacancies: list[dict]) -> tuple[int, int, int]:
        """
        Добавляет список вакансий (каждая — словарь).
        Возвращает кортеж (добавлено_новых, ошибок_при_добавлении, всего_попыток).
        """
        added = error = 0
        for vacancy in vacancies:
            try:
                if self.add_vacancy(vacancy):
                    added += 1
                else:
                    logger.info(f"Дубликат - {vacancy.get('url')}")
            except Exception as e:
                logger.error(f"Ошибка при добавлении {vacancy.get('name')}, {e}")
                error += 1
        return added, error, len(vacancies)

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[dict]:
        """Возвращает все вакансии (сортировка по id DESC)."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM vacancies ORDER BY id DESC"
            if limit is not None:
                query += " LIMIT %s OFFSET %s"
                cur.execute(query, (limit, offset))
            else:
                cur.execute(query)
            return cur.fetchall()

    def get_by_url(self, url: str) -> dict | None:
        """Возвращает вакансию по URL или None."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM vacancies WHERE url = %s"
            cur.execute(query, (url,))
            return cur.fetchone()

    def get_by_date(self, start_date: str, end_date: str) -> list[dict]:
        """Возвращает вакансии за диапазон дат (collected_at)."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM vacancies WHERE collected_at BETWEEN %s AND %s"
            if len(end_date) == 10:
                end_date += "T23:59:59.999999"
            cur.execute(query, (start_date, end_date))
            return cur.fetchall()

    def count(self) -> int:
        """Возвращает общее количество записей."""
        with self.conn.cursor() as cur:
            query = "SELECT COUNT(*) FROM vacancies"
            cur.execute(query)
            return cur.fetchone()[0]

    def exists(self, url: str) -> bool:
        """Проверяет, есть ли уже вакансия с данным URL."""
        with self.conn.cursor() as cur:
            query = "SELECT EXISTS(SELECT 1 FROM vacancies WHERE url = %s);"
            cur.execute(query, (url,))
            return cur.fetchone()[0]

    def close(self) -> None:
        """Закрывает соединение с БД."""
        if self.conn and not self.conn.closed:
            self.conn.close()

    # Поддержка контекстного менеджера
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
