"""Периоды отчёта: календарные границы, CLI и закреплённая статистика."""

import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import main
from src.tools.stats_tool import REPORT_PERIODS, GetStatsTool, _period_start


class ReportPeriodTests(unittest.TestCase):
    """Проверки без LLM, HH и реального соединения с БД."""

    def test_calendar_boundaries(self) -> None:
        """Короткий месяц и високосный год не ломают границы периода."""
        now = datetime(2026, 5, 31, 12, tzinfo=timezone.utc)
        for period, start in (
            ("30d", now - timedelta(days=30)),
            ("3m", now.replace(month=2, day=28)),
            ("6m", now.replace(year=2025, month=11, day=30)),
            ("1y", now.replace(year=2025)),
        ):
            with self.subTest(period=period):
                self.assertEqual(_period_start(period, now), start)
        leap = now.replace(year=2024, month=2, day=29)
        self.assertEqual(_period_start("1y", leap), leap.replace(year=2023, day=28))

    def test_cli_defaults_choices_and_all_hh_forwarding(self) -> None:
        """Обе команды принимают периоды; all-hh передаёт период после сбора."""
        parser = main._build_parser()
        for command in ("report", "all-hh"):
            args = [command, "--spec", "network_engineer"]
            self.assertEqual(parser.parse_args(args).period, "1y")
            for period in REPORT_PERIODS:
                self.assertEqual(
                    parser.parse_args([*args, "--period", period]).period, period
                )
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args([*args, "--period", "invalid"])
        calls = []
        with (
            patch("main._load_report_configuration"),
            patch(
                "main.cmd_collect_hh", side_effect=lambda *args: calls.append("collect")
            ),
            patch(
                "main.cmd_report",
                side_effect=lambda *args, **kwargs: calls.append("report"),
            ) as report,
        ):
            main.cmd_all_hh(5, "network_engineer", period="3m")
        self.assertEqual(calls, ["collect", "report"])
        report.assert_called_once_with("network_engineer", period="3m")

    def test_tool_pins_role_period_and_data_before_writer(self) -> None:
        """Данные и границы фиксируются одним запросом; неверный период не идёт в БД."""
        now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        with (
            patch("src.tools.stats_tool.VacancyStorage") as factory,
            patch("src.tools.stats_tool.datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = now
            storage = factory.return_value.__enter__.return_value
            storage.get_for_report.return_value = [
                {"url": "test", "requirements": "Linux"}
            ]
            tool = GetStatsTool(
                professional_role=112, skills_keywords=["Linux"], period="3m"
            )
            self.assertTrue(tool.prepare())
            payload = tool._run()
            self.assertEqual(tool._run(), payload)
            data = json.loads(payload)
            self.assertEqual(data["stats"]["total"], 1)
            self.assertEqual(data["period"]["end"], now.isoformat())
            storage.get_for_report.assert_called_once_with(
                112, now.replace(month=7), now
            )
            factory.reset_mock()
            with self.assertRaises(ValueError):
                GetStatsTool(
                    professional_role=112, skills_keywords=["Linux"], period="invalid"
                ).prepare()
            factory.assert_not_called()
