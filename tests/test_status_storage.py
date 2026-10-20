"""Проверки SQL и транзакций хранилища без реального соединения."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg2
from psycopg2 import sql

from src.collectors.vacancy_status import ACTIVE_CHECK_INTERVAL, UNKNOWN_RETRY_INTERVAL
from src.storage import VacancyStorage


class StatusStorageTests(unittest.TestCase):
    """Новый фильтр дополняет существующие условия, записи транзакционны."""

    def setUp(self) -> None:
        """Создаёт хранилище с подменённым соединением без DDL."""
        self.storage = object.__new__(VacancyStorage)
        self.storage.conn = MagicMock()
        self.cursor = self.storage.conn.cursor.return_value.__enter__.return_value
        self.cursor.fetchall.return_value = []

    def test_match_sql_preserves_filters_and_parameters(self) -> None:
        """SQL сохраняет опыт и статус; зарплата и город проверяются в Python."""
        resume = {
            "experience_years": 5,
            "salary_min": 100_000,
            "city": "Москва",
            "ready_to_relocate": False,
        }
        self.storage.find_top_vacancies([0.1, 0.2], resume, top_n=7)
        query, params = self.cursor.execute.call_args.args
        self.assertIn(
            "a.embedding IS NOT NULL AND (v.experience = ANY(%s) OR v.experience IS NULL)",
            query,
        )
        self.assertNotIn("v.salary_to >= %s", query)
        self.assertNotIn("v.city = %s", query)
        self.assertIn("AND v.status IN ('active', 'unknown')", query)
        self.assertIn("v.status, v.last_checked_at", query)
        self.assertIn("v.salary_to, v.salary_currency", query)
        self.assertIn("ORDER BY a.embedding <=> %s::vector", query)
        self.assertIn("LIMIT %s", query)
        self.assertEqual(
            params,
            [
                "[0.1,0.2]",
                "[0.1,0.2]",
                ["between1And3", "between3And6"],
                "[0.1,0.2]",
                100,
            ],
        )

    def test_match_with_missing_resume_filters(self) -> None:
        """Статус применяется и без дополнительных параметров резюме."""
        self.storage.find_top_vacancies([0.1], {}, top_n=1)
        query, params = self.cursor.execute.call_args.args
        self.assertIn(
            "WHERE a.embedding IS NOT NULL AND v.status IN ('active', 'unknown')", query
        )
        self.assertEqual(params, ["[0.1]", "[0.1]", "[0.1]", 100])

    def test_zero_and_negative_top_do_not_query(self) -> None:
        """Пустой топ не читает БД; отрицательный предел отвергается."""
        self.assertEqual(self.storage.find_top_vacancies([0.1], {}, top_n=0), [])
        with self.assertRaises(ValueError):
            self.storage.find_top_vacancies([0.1], {}, top_n=-1)
        self.cursor.execute.assert_not_called()

    def test_due_sql_has_intervals_order_and_limit(self) -> None:
        """Архив исключён; непроверенные идут первыми, выборка ограничена."""
        self.storage.get_due_for_status_check(limit=3)
        query, params = self.cursor.execute.call_args.args
        self.assertIn("status IN ('active', 'unknown')", query)
        self.assertIn("last_checked_at IS NULL", query)
        self.assertIn("ORDER BY last_checked_at ASC NULLS FIRST, id ASC", query)
        self.assertIn("LIMIT %s", query)
        self.assertEqual(params, (ACTIVE_CHECK_INTERVAL, UNKNOWN_RETRY_INTERVAL, 3))
        with self.assertRaises(ValueError):
            self.storage.get_due_for_status_check(limit=0)

    def test_status_update_commits_actual_timestamp(self) -> None:
        """Время последней попытки берётся из БД и возвращается вызывающему."""
        now = datetime.now(timezone.utc)
        self.cursor.fetchone.return_value = (now,)
        self.assertEqual(self.storage.update_vacancy_status("url", "unknown"), now)
        query, params = self.cursor.execute.call_args.args
        self.assertIn("clock_timestamp()", query)
        self.assertEqual(params, ("unknown", "url"))
        self.storage.conn.commit.assert_called_once()
        self.storage.conn.rollback.assert_not_called()
        self.cursor.fetchone.return_value = None
        self.assertIsNone(self.storage.update_vacancy_status("missing", "active"))

    def test_status_update_rolls_back_and_reraises(self) -> None:
        """Ошибка БД не превращается в успешный результат."""
        self.cursor.execute.side_effect = psycopg2.OperationalError("write failed")
        with self.assertRaises(psycopg2.OperationalError):
            self.storage.update_vacancy_status("url", "archived")
        self.storage.conn.rollback.assert_called_once()
        self.storage.conn.commit.assert_not_called()

    def test_invalid_status_does_not_write(self) -> None:
        """Недопустимый статус отвергается до SQL."""
        with self.assertRaises(ValueError):
            self.storage.update_vacancy_status("url", "closed")
        self.cursor.execute.assert_not_called()

    def test_insert_keeps_defaults_and_duplicate_semantics(self) -> None:
        """Вставка без метаданных остаётся unknown; дубликат не обновляется."""
        self.cursor.rowcount = 1
        self.assertTrue(
            self.storage.add_vacancy(
                {"url": "url", "name": "Инженер", "employer": "Компания"}
            )
        )
        query, params = self.cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (url) DO NOTHING", query)
        self.assertEqual(params[-2:], ("unknown", None))
        self.assertEqual(query.count("%s"), len(params))
        self.cursor.rowcount = 0
        self.assertFalse(
            self.storage.add_vacancy(
                {"url": "url", "name": "Инженер", "employer": "Компания"}
            )
        )

    def test_insert_preserves_collection_status_and_time(self) -> None:
        """Статус и дата сборщика записываются вместе с вакансией."""
        checked_at = datetime.now(timezone.utc)
        self.cursor.rowcount = 1
        self.storage.add_vacancy(
            {
                "url": "url",
                "name": "Инженер",
                "employer": "Компания",
                "status": "active",
                "last_checked_at": checked_at,
            }
        )
        query, params = self.cursor.execute.call_args.args
        self.assertEqual(params[-2:], ("active", checked_at))
        self.assertEqual(query.count("%s"), len(params))

    def test_insert_invalid_status_rejected_before_sql(self) -> None:
        """Ошибка статуса не вызывает SQL и не сохраняет запись."""
        with self.assertRaises(ValueError):
            self.storage.add_vacancy(
                {
                    "url": "url",
                    "name": "Инженер",
                    "employer": "Компания",
                    "status": "closed",
                }
            )
        self.cursor.execute.assert_not_called()


@unittest.skipUnless(os.getenv("VACANCY_STATUS_TEST_DSN"), "Тестовая БД не задана")
class StatusStorageDatabaseTests(unittest.TestCase):
    """Проверки PostgreSQL в собственной временной схеме, без данных public."""

    def setUp(self) -> None:
        """Создаёт изолированную схему в явно выбранной тестовой БД."""
        self.conn = psycopg2.connect(os.environ["VACANCY_STATUS_TEST_DSN"])
        self.addCleanup(self.conn.close)
        self.schema = "test_vacancy_status_" + uuid4().hex
        with self.conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(self.schema)
                )
            )
        self.conn.commit()
        self.addCleanup(self._remove_schema)
        self.storage = object.__new__(VacancyStorage)
        self.storage.conn = self.conn

    def _remove_schema(self) -> None:
        """Удаляет только временную схему, созданную этим тестом."""
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )
        self.conn.commit()

    def test_date_ranges_compare_instants_and_include_end_day(self) -> None:
        """UTC, +03:00 и календарный день выбирают одинаковые записи на границах."""
        self.storage._create_table()
        with self.conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'Europe/Moscow'")
            for url, collected_at in (
                ("start", "2026-10-19T21:00:00+00:00"),
                ("end", "2026-10-20T20:59:59.999999+00:00"),
                ("outside", "2026-10-20T21:00:00+00:00"),
            ):
                cur.execute(
                    "INSERT INTO vacancies (url, name, employer, collected_at) "
                    "VALUES (%s, 'Test', 'Test', %s)",
                    (url, collected_at),
                )
        for start, end in (
            ("2026-10-19T21:00:00+00:00", "2026-10-20T20:59:59.999999+00:00"),
            ("2026-10-20T00:00:00+03:00", "2026-10-20T23:59:59.999999+03:00"),
            ("2026-10-20", "2026-10-20"),
        ):
            with self.subTest(start=start, end=end):
                rows = self.storage.get_by_date(start, end)
                self.assertEqual({row["url"] for row in rows}, {"start", "end"})

    def test_report_filters_role_period_and_keeps_all_statuses(self) -> None:
        """Другие роли, NULL и записи за границами периода не входят в отчёт."""
        self.storage._create_table()
        start = datetime(2026, 9, 20, tzinfo=timezone.utc)
        end = start.replace(month=10)
        with self.conn.cursor() as cur:
            for url, role, status, collected_at in (
                ("start", 112, "active", start),
                ("end", 112, "archived", end),
                ("middle", 112, "unknown", start.replace(day=25)),
                ("old", 112, "active", start.replace(day=19)),
                ("future", 112, "active", end.replace(day=21)),
                ("other", 160, "active", start),
                ("no_role", None, "active", start),
            ):
                cur.execute(
                    "INSERT INTO vacancies (url, name, employer, professional_role, "
                    "status, collected_at) VALUES (%s, 'Test', 'Test', %s, %s, %s)",
                    (url, role, status, collected_at.isoformat()),
                )
        rows = self.storage.get_for_report(112, start, end)
        self.assertEqual([row["url"] for row in rows], ["middle", "end", "start"])

    def test_schema_defaults_constraints_and_existing_data(self) -> None:
        """Новая схема задаёт defaults и сохраняет данные при повторном DDL."""
        self.storage._create_table()
        self.storage.add_vacancy(
            {"url": "existing", "name": "Инженер", "employer": "Компания"}
        )
        saved = self.storage.get_by_url("existing")
        self.assertEqual(saved["status"], "unknown")
        self.assertIsNone(saved["last_checked_at"])
        self.storage._create_table()
        self.assertEqual(self.storage.get_by_url("existing"), saved)
        with self.conn.cursor() as cur:
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute("UPDATE vacancies SET status='invalid'")
        self.conn.rollback()
        self.assertEqual(self.storage.get_by_url("existing"), saved)

    def test_real_due_selection_and_match_filters(self) -> None:
        """Сроки, фильтры и исключение архива работают в PostgreSQL."""
        self.storage._create_table()
        vector = [1.0] + [0.0] * 2559
        cases = [
            ("never", "unknown", None, "Москва", 200_000, "between3And6", None),
            ("active_due", "active", "8 days", "Москва", 200_000, "between3And6", None),
            (
                "unknown_due",
                "unknown",
                "2 days",
                "Москва",
                200_000,
                "between3And6",
                None,
            ),
            (
                "active_fresh",
                "active",
                "1 hour",
                "Москва",
                200_000,
                "between3And6",
                None,
            ),
            (
                "unknown_fresh",
                "unknown",
                "1 hour",
                "Москва",
                200_000,
                "between3And6",
                None,
            ),
            ("archived", "archived", None, "Москва", 200_000, "between3And6", None),
            ("low_salary", "unknown", "1 hour", "Москва", 50_000, "between3And6", None),
            (
                "wrong_city",
                "unknown",
                "1 hour",
                "Казань",
                200_000,
                "between3And6",
                "ON_SITE",
            ),
            ("remote", "unknown", "1 hour", "Казань", None, "between3And6", "REMOTE"),
            (
                "unspecified_experience",
                "unknown",
                "1 hour",
                "Москва",
                200_000,
                None,
                None,
            ),
            (
                "office",
                "unknown",
                "1 hour",
                "Москва",
                200_000,
                "between3And6",
                "ON_SITE",
            ),
            (
                "other_currency",
                "unknown",
                "1 hour",
                "Москва",
                2_000,
                "between3And6",
                None,
            ),
            ("hourly", "unknown", "1 hour", "Москва", 1_000, "between3And6", None),
            (
                "unknown_currency",
                "unknown",
                "1 hour",
                "Москва",
                1_000,
                "between3And6",
                None,
            ),
            (
                "wrong_experience",
                "unknown",
                "1 hour",
                "Москва",
                200_000,
                "moreThan6",
                None,
            ),
        ]
        for url, status, age, city, salary, experience, work_format in cases:
            self.storage.add_vacancy(
                {
                    "url": url,
                    "name": "Инженер",
                    "employer": "Компания",
                    "city": city,
                    "salary_to": salary,
                    "salary_currency": (
                        None
                        if url == "unknown_currency"
                        else "USD"
                        if url == "other_currency"
                        else "RUR"
                    ),
                    "salary": (
                        f"до {salary} в час"
                        if url == "hourly"
                        else f"до {salary} в месяц"
                    ),
                    "experience": experience,
                    "work_format": work_format,
                }
            )
            vacancy_id = self.storage.get_by_url(url)["id"]
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE vacancies SET status=%s, last_checked_at=statement_timestamp() - %s::interval WHERE id=%s",
                    (status, age, vacancy_id),
                )
                cur.execute(
                    "INSERT INTO vacancy_analysis (vacancy_id, analyzed_at) VALUES (%s, '2026-10-14')",
                    (vacancy_id,),
                )
            self.conn.commit()
            self.storage.save_embedding(vacancy_id, "text", vector, "model")
        due = self.storage.get_due_for_status_check(limit=20)
        self.assertEqual(
            [v["url"] for v in due], ["never", "active_due", "unknown_due"]
        )
        self.assertEqual(
            [v["url"] for v in self.storage.get_due_for_status_check(limit=1)],
            ["never"],
        )
        matches = self.storage.find_top_vacancies(
            vector,
            {
                "experience_years": 5,
                "salary_min": 100_000,
                "salary_expectation": "от 100000 ₽",
                "work_format": "REMOTE,HYBRID",
                "city": "Москва",
            },
        )
        self.assertEqual(
            {v["url"] for v in matches},
            {
                "never",
                "active_due",
                "unknown_due",
                "active_fresh",
                "unknown_fresh",
                "remote",
                "unspecified_experience",
                "other_currency",
                "hourly",
                "unknown_currency",
            },
        )
        checked_at = self.storage.update_vacancy_status("never", "archived")
        self.assertIsNotNone(checked_at.tzinfo)
        self.assertNotIn(
            "never", {v["url"] for v in self.storage.find_top_vacancies(vector, {})}
        )
        self.assertEqual(self.storage.get_by_url("never")["name"], "Инженер")

    def test_real_match_pagination_with_equal_distances(self) -> None:
        """SQL-страницы пересекают одинаковые расстояния без пропусков по ID."""
        self.storage._create_table()
        vector = [1.0] + [0.0] * 2559
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vacancies (
                    url, name, employer, work_format, collected_at, status
                )
                SELECT
                    'page-' || n, 'Инженер', 'Компания',
                    CASE WHEN n <= 200 THEN 'ON_SITE' ELSE 'REMOTE' END,
                    '2026-10-19', 'active'
                FROM generate_series(1, 205) AS series(n)
            """)
            cur.execute(
                """
                INSERT INTO vacancy_analysis (vacancy_id, analyzed_at, embedding)
                SELECT id, '2026-10-19', %s::vector FROM vacancies
                """,
                (self.storage._serialize_vector(vector),),
            )
        self.conn.commit()

        resume = {"work_format": "REMOTE,HYBRID"}
        matches = self.storage.find_top_vacancies(vector, resume, top_n=3)
        self.assertEqual(
            [v["url"] for v in matches], ["page-201", "page-202", "page-203"]
        )
        self.assertTrue(all("_match_distance" not in v for v in matches))
        self.storage.update_vacancy_status("page-201", "archived")
        matches = self.storage.find_top_vacancies(vector, resume, top_n=3)
        self.assertEqual(
            [v["url"] for v in matches], ["page-202", "page-203", "page-204"]
        )

    def test_collection_metadata_saved_without_updating_duplicate(self) -> None:
        """Собранная новая запись активна; дубликат не меняет дату и статус."""
        self.storage._create_table()
        checked_at = datetime.now(timezone.utc)
        vacancy = {
            "url": "collected",
            "name": "Инженер",
            "employer": "Компания",
            "status": "active",
            "last_checked_at": checked_at,
        }
        self.assertTrue(self.storage.add_vacancy(vacancy))
        saved = self.storage.get_by_url("collected")
        self.assertEqual(saved["status"], "active")
        self.assertEqual(saved["last_checked_at"], checked_at)
        self.assertEqual(self.storage.get_due_for_status_check(), [])
        archived_at = self.storage.update_vacancy_status("collected", "archived")
        self.assertFalse(self.storage.add_vacancy(vacancy))
        duplicate = self.storage.get_by_url("collected")
        self.assertEqual(duplicate["status"], "archived")
        self.assertEqual(duplicate["last_checked_at"], archived_at)
        self.assertEqual(duplicate["collected_at"], saved["collected_at"])
