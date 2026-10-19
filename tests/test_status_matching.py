"""Проверки добора и отображения актуальности без внешних сервисов."""

import contextlib
import io
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import main
from src.collectors.vacancy_status import StatusCheckConfigError
from src.matching.match_report import build_match_report
from src.matching.matcher import match_resume
from src.storage import VacancyStorage

NOW = datetime.now(timezone.utc)


class StatusMatchingTests(unittest.TestCase):
    """Матчинг добирает результаты после исключения архива."""

    def test_refill_beyond_twice_top_n_without_rechecking(self) -> None:
        """Восемь архивных кандидатов не мешают вернуть два активных."""
        rows = [
            {
                "id": i,
                "url": str(i),
                "status": "unknown",
                "last_checked_at": None,
                "score": 1 - i / 100,
            }
            for i in range(12)
        ]
        storage = MagicMock()
        storage.get_resume.return_value = {"id": 1, "embedding": "[0.1,0.2]"}

        def find(embedding: list[float], resume: dict, top_n: int) -> list[dict]:
            """Имитирует SQL с исключением уже сохранённого архива."""
            return [dict(row) for row in rows if row["status"] != "archived"][:top_n]

        def save(url: str, status: str) -> datetime:
            """Сохраняет статус в имитации БД."""
            rows[int(url)].update(status=status, last_checked_at=NOW)
            return NOW

        storage.find_top_vacancies.side_effect = find
        storage.update_vacancy_status.side_effect = save
        with (
            patch("src.matching.matcher.VacancyStorage") as factory,
            patch("src.matching.matcher.create_status_session"),
            patch(
                "src.matching.matcher.check_vacancy_status",
                side_effect=lambda url, session: (
                    "archived" if int(url) < 8 else "active"
                ),
            ) as check,
            patch("src.matching.matcher.time.sleep"),
        ):
            factory.return_value.__enter__.return_value = storage
            _, matches = match_resume(1, top_n=2)
        self.assertEqual([m["id"] for m in matches], [8, 9])
        self.assertEqual(check.call_count, 10)
        self.assertEqual(len({call.args[0] for call in check.call_args_list}), 10)
        self.assertTrue(
            all(
                call.kwargs["top_n"] == 2
                for call in storage.find_top_vacancies.call_args_list
            )
        )
        self.assertTrue(all(m["last_checked_at"] == NOW for m in matches))

    def test_python_filters_and_archive_refill_together(self) -> None:
        """Реальные фильтры добирают топ после неподходящих записей и архива."""
        rows = [
            {
                "id": i,
                "url": str(i),
                "work_format": "ON_SITE" if i < 200 else "REMOTE",
                "city": "Москва",
                "salary_to": 200_000,
                "salary_currency": "RUR",
                "salary": "до 200000 ₽ в месяц",
                "status": "unknown",
                "last_checked_at": None,
                "score": 1 - i / 1000,
                "_match_distance": i / 1000,
            }
            for i in range(205)
        ]
        rows[201].update(salary_to=2_000, salary_currency="USD")
        rows[202].update(salary_to=1_000, salary="до 1000 ₽ в час")
        rows[203].update(salary_to=50_000, salary="до 50000 ₽ в месяц")
        storage = object.__new__(VacancyStorage)
        storage.conn = MagicMock()
        cursor = storage.conn.cursor.return_value.__enter__.return_value

        def execute(query: str, params: list) -> None:
            """SQL-страницы продолжаются по позиции, исключая сохранённый архив."""
            self.assertIn("LIMIT %s", query)
            self.assertEqual(params[-1], 100)
            eligible = [row for row in rows if row["status"] != "archived"]
            if "> (%s, %s)" in query:
                after = tuple(params[-4:-2])
                eligible = [
                    row
                    for row in eligible
                    if (row["_match_distance"], row["id"]) > after
                ]
            cursor.fetchall.return_value = [dict(row) for row in eligible[: params[-1]]]

        def save(url: str, status: str) -> datetime:
            """Запоминает архив для следующего запроса поиска."""
            rows[int(url)].update(status=status, last_checked_at=NOW)
            return NOW

        cursor.execute.side_effect = execute
        resume = {
            "id": 5,
            "embedding": [0.1, 0.2],
            "work_format": "REMOTE,HYBRID",
            "city": "Казань",
            "salary_min": 100_000,
            "salary_expectation": "от 100000 ₽",
        }
        with (
            patch("src.matching.matcher.VacancyStorage") as factory,
            patch.object(storage, "get_resume", return_value=resume),
            patch.object(storage, "update_vacancy_status", side_effect=save),
            patch("src.matching.matcher.create_status_session"),
            patch("src.matching.matcher.time.sleep"),
            patch(
                "src.matching.matcher.check_vacancy_status",
                side_effect=lambda url, session: (
                    "archived" if url == "200" else "active"
                ),
            ) as check,
        ):
            factory.return_value.__enter__.return_value = storage
            _, matches = match_resume(5, top_n=3)
        self.assertEqual([m["id"] for m in matches], [201, 202, 204])
        self.assertEqual(
            [call.args[0] for call in check.call_args_list],
            ["200", "201", "202", "204"],
        )
        self.assertEqual(cursor.execute.call_count, 6)
        self.assertTrue(all("_match_distance" not in row for row in matches))

    def test_exhaustion_and_fresh_candidates(self) -> None:
        """Возвращается неполный топ без запроса свежих записей."""
        fresh = {
            "id": 1,
            "url": "fresh",
            "status": "active",
            "last_checked_at": NOW,
            "score": 0.9,
        }
        stale = {
            "id": 2,
            "url": "stale",
            "status": "active",
            "last_checked_at": NOW - timedelta(days=8),
            "score": 0.8,
        }
        with (
            patch("src.matching.matcher.VacancyStorage") as factory,
            patch("src.matching.matcher.create_status_session"),
            patch(
                "src.matching.matcher.check_vacancy_status", return_value="archived"
            ) as check,
            patch("src.matching.matcher.time.sleep") as sleep,
        ):
            storage = factory.return_value.__enter__.return_value
            storage.get_resume.return_value = {"embedding": [0.1]}
            storage.find_top_vacancies.side_effect = [[fresh, stale], [fresh]]
            storage.update_vacancy_status.return_value = NOW
            _, matches = match_resume(1, top_n=3)
            self.assertEqual(matches, [fresh])
            check.assert_called_once()
            self.assertEqual(check.call_args.args[0], "stale")
            sleep.assert_not_called()

    def test_unknown_kept_and_zero_top_has_no_requests(self) -> None:
        """Неудачная проверка остаётся в выдаче; нулевой топ не загружает URL."""
        with (
            patch("src.matching.matcher.VacancyStorage") as factory,
            patch("src.matching.matcher.create_status_session"),
            patch(
                "src.matching.matcher.check_vacancy_status", return_value="unknown"
            ) as check,
        ):
            storage = factory.return_value.__enter__.return_value
            storage.get_resume.return_value = {"embedding": [0.1]}
            storage.find_top_vacancies.return_value = [
                {"url": "a", "status": "active", "last_checked_at": None}
            ]
            storage.update_vacancy_status.return_value = NOW
            _, matches = match_resume(1, top_n=1)
            self.assertEqual(matches[0]["status"], "unknown")
            self.assertEqual(matches[0]["last_checked_at"], NOW)
            check.reset_mock()
            storage.find_top_vacancies.reset_mock()
            self.assertEqual(match_resume(1, top_n=0)[1], [])
            check.assert_not_called()
            storage.find_top_vacancies.assert_not_called()

    def test_cli_limit_and_dispatch(self) -> None:
        """Новая команда ограничена; прежние defaults сохранены."""
        parser = main._build_parser()
        self.assertEqual(parser.parse_args(["check-status"]).n, 20)
        self.assertEqual(parser.parse_args(["match", "--resume-id", "1"]).top, 20)
        self.assertEqual(parser.parse_args(["collect-hh", "--spec", "security"]).n, 10)
        self.assertIsNone(parser.parse_args(["analyze"]).n)
        for value in ("0", "-1", "abc"):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as exc,
            ):
                parser.parse_args(["check-status", "--n", value])
            self.assertEqual(exc.exception.code, 2)
        with (
            patch("sys.argv", ["main.py", "check-status", "--n", "3"]),
            patch("main.cmd_check_status") as command,
        ):
            main.main()
            command.assert_called_once_with(3)

    def test_cli_cookie_error_and_batch_summary(self) -> None:
        """Нет traceback при отсутствии cookies; счётчики и пустота видимы."""
        with (
            patch("sys.argv", ["main.py", "check-status"]),
            patch(
                "main.cmd_check_status",
                side_effect=StatusCheckConfigError("нужны HH_TOKEN и HH_XSRF"),
            ),
            contextlib.redirect_stderr(io.StringIO()) as error,
            self.assertRaises(SystemExit) as exc,
        ):
            main.main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("HH_TOKEN", error.getvalue())
        with (
            patch(
                "main.check_vacancy_statuses",
                return_value={"active": 1, "archived": 2, "unknown": 3},
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            main.cmd_check_status(6)
        self.assertIn("Проверено: 6", output.getvalue())
        with (
            patch(
                "main.check_vacancy_statuses",
                return_value=dict.fromkeys(("active", "archived", "unknown"), 0),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            main.cmd_check_status()
        self.assertIn("Нет вакансий", output.getvalue())

    def test_report_legacy_unknown_and_checked_date(self) -> None:
        """Старые входные словари помечаются непроверенными."""
        legacy = {"name": "Инженер", "score": 0.8, "url": "https://hh.ru/vacancy/1"}
        report = build_match_report({"id": 1}, [legacy])
        self.assertIn("Актуальность не подтверждена", report)
        self.assertIn("не выполнялась", report)
        checked = dict(legacy, status="active", last_checked_at=NOW)
        report = build_match_report({"id": 1}, [checked])
        self.assertIn("Активна", report)
        self.assertIn(NOW.strftime("%Y-%m-%d %H:%M %z"), report)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main._print_match(1, legacy)
        self.assertIn("Актуальность не подтверждена", output.getvalue())

    def test_match_saves_one_report_including_empty_results(self) -> None:
        """CLI пишет один полный отчёт даже без вакансий."""
        from pathlib import Path

        for matches in ([], [{"name": "Инженер", "score": 0.8}]):
            with self.subTest(empty=not matches), TemporaryDirectory() as directory:
                target = Path(directory) / "outputs"
                with (
                    patch("main.OUTPUTS_DIR", str(target)),
                    patch("main.match_resume", return_value=({"id": 1}, matches)),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    main.cmd_match(1)
                files = list(target.glob("*.md"))
                self.assertEqual(len(files), 1)
                self.assertIn("# Подбор вакансий", files[0].read_text())
