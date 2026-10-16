"""Проверки актуальности без реальных HTTP-запросов и подключения к БД."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import requests

from src.collectors.vacancy_status import (
    StatusCheckConfigError,
    check_vacancy_status,
    check_vacancy_statuses,
    classify_vacancy_page,
    create_status_session,
    needs_status_check,
)

ACTIVE_HTML = (
    '<template id="HH-Lux-InitialState">'
    '{"vacancyView": {"description": "Описание вакансии"}}'
    "</template><h1>Инженер</h1>"
)
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


class VacancyStatusTests(unittest.TestCase):
    """Три исхода проверки и сроки повторного обращения."""

    def test_classification(self) -> None:
        """Архивный маркер важнее vacancyView; прочие страницы неизвестны."""
        cases = [
            (ACTIVE_HTML, "active"),
            (ACTIVE_HTML + "ВАКАНСИЯ В АРХИВЕ", "archived"),
            ("<p>В архиве с 12 октября</p>", "archived"),
            ("x" * 16_000 + " вакансия в архиве", "archived"),
            ("<h1>Войдите в аккаунт</h1>", "unknown"),
            ("<h1>Подтвердите, что вы человек</h1>", "unknown"),
            ("<template id='HH-Lux-InitialState'>{broken</template>", "unknown"),
            ("<template id='HH-Lux-InitialState'>[]</template>", "unknown"),
            (
                "<template id='HH-Lux-InitialState'>{\"vacancyView\": {}}</template>",
                "unknown",
            ),
            (
                "<template id='HH-Lux-InitialState'>{\"vacancyView\": true}</template>",
                "unknown",
            ),
            ("", "unknown"),
            (ACTIVE_HTML + "<script>вакансия в архиве</script>", "active"),
        ]
        for html, expected in cases:
            with self.subTest(expected=expected, html=html[:80]):
                self.assertEqual(classify_vacancy_page(html), expected)

    def test_http_errors_are_unknown_even_with_archive_marker(self) -> None:
        """Текст ошибочного ответа не подтверждает архив."""
        for code in (403, 429, 500):
            with self.subTest(code=code):
                session = MagicMock(spec=requests.Session)
                response = requests.Response()
                response.status_code = code
                response._content = "вакансия в архиве".encode()
                session.get.return_value = response
                self.assertEqual(
                    check_vacancy_status("https://hh.ru/vacancy/1", session), "unknown"
                )
                session.get.assert_called_once_with(
                    "https://hh.ru/vacancy/1", timeout=15
                )

    def test_request_failure_and_recovery(self) -> None:
        """После неудачной попытки отдельный вызов может подтвердить active."""
        session = MagicMock(spec=requests.Session)
        response = requests.Response()
        response.status_code = 200
        response._content = ACTIVE_HTML.encode()
        response.encoding = "utf-8"
        session.get.side_effect = [requests.Timeout("timeout"), response]
        self.assertEqual(check_vacancy_status("url", session), "unknown")
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(check_vacancy_status("url", session), "active")

    def test_intervals(self) -> None:
        """Проверки наступают ровно через семь дней или сутки."""
        for status, days in (("active", 7), ("unknown", 1)):
            with self.subTest(status=status):
                vacancy = {
                    "status": status,
                    "last_checked_at": NOW - timedelta(days=days),
                }
                self.assertTrue(needs_status_check(vacancy, NOW))
                vacancy["last_checked_at"] += timedelta(microseconds=1)
                self.assertFalse(needs_status_check(vacancy, NOW))
        self.assertTrue(
            needs_status_check({"status": "unknown", "last_checked_at": None}, NOW)
        )
        self.assertFalse(
            needs_status_check({"status": "archived", "last_checked_at": None}, NOW)
        )
        self.assertFalse(
            needs_status_check(
                {"status": "archived", "last_checked_at": NOW - timedelta(days=30)}, NOW
            )
        )

    def test_cookies_required_without_anonymous_fallback(self) -> None:
        """Отсутствие одной cookie останавливает проверку до создания сессии."""
        for token, xsrf in (("", ""), ("token", ""), ("", "xsrf")):
            with self.subTest(token=bool(token), xsrf=bool(xsrf)):
                with patch.dict(os.environ, {"HH_TOKEN": token, "HH_XSRF": xsrf}):
                    with self.assertRaises(StatusCheckConfigError):
                        create_status_session()

    def test_batch_is_limited_and_counts_saved_outcomes(self) -> None:
        """Одна выбранная порция обрабатывается без добора."""
        with (
            patch("src.collectors.vacancy_status.create_status_session"),
            patch("src.storage.VacancyStorage") as factory,
            patch(
                "src.collectors.vacancy_status.check_vacancy_status",
                side_effect=["archived", "unknown"],
            ) as check,
            patch("src.collectors.vacancy_status.time.sleep") as sleep,
        ):
            storage = factory.return_value.__enter__.return_value
            storage.get_due_for_status_check.return_value = [{"url": "a"}, {"url": "b"}]
            storage.update_vacancy_status.return_value = NOW
            counts = check_vacancy_statuses(n=2)
            self.assertEqual(counts, {"active": 0, "archived": 1, "unknown": 1})
            storage.get_due_for_status_check.assert_called_once_with(limit=2)
            self.assertEqual(check.call_count, 2)
            sleep.assert_called_once_with(1.5)

    def test_empty_batch_and_missing_rows(self) -> None:
        """Пустая порция не делает запросы, исчезнувшая строка не считается."""
        with (
            patch("src.collectors.vacancy_status.create_status_session"),
            patch("src.storage.VacancyStorage") as factory,
            patch(
                "src.collectors.vacancy_status.check_vacancy_status",
                return_value="active",
            ) as check,
        ):
            storage = factory.return_value.__enter__.return_value
            storage.get_due_for_status_check.return_value = []
            self.assertEqual(sum(check_vacancy_statuses().values()), 0)
            check.assert_not_called()
            storage.get_due_for_status_check.return_value = [{"url": "a"}]
            storage.update_vacancy_status.return_value = None
            self.assertEqual(sum(check_vacancy_statuses().values()), 0)

    def test_batch_database_failure_is_not_suppressed(self) -> None:
        """Ошибка сохранения останавливает порцию вместо успешного счётчика."""
        with (
            patch("src.collectors.vacancy_status.create_status_session"),
            patch("src.storage.VacancyStorage") as factory,
            patch(
                "src.collectors.vacancy_status.check_vacancy_status",
                return_value="unknown",
            ),
        ):
            storage = factory.return_value.__enter__.return_value
            storage.get_due_for_status_check.return_value = [{"url": "a"}]
            storage.update_vacancy_status.side_effect = RuntimeError("write failed")
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                check_vacancy_statuses(n=1)

    def test_nonpositive_batch_rejected_before_services(self) -> None:
        """Неположительный лимит не запускает проверку."""
        with patch("src.collectors.vacancy_status.create_status_session") as session:
            for n in (0, -1):
                with self.assertRaises(ValueError):
                    check_vacancy_statuses(n)
            session.assert_not_called()
