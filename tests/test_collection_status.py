"""Проверки статуса новых вакансий без БД, HH, Serper и LLM."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.collectors.pipeline import collect_hh, collect_serper

CHECKED_AT = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


class CollectionStatusTests(unittest.TestCase):
    """Успешная загрузка отмечает новую запись, дубликат не проверяется."""

    def test_hh_new_active_and_duplicate_skipped(self) -> None:
        """Детали загружаются только для новой записи; статус и дата передаются."""
        client = MagicMock()
        client.search.return_value = [{"vacancyId": 1}, {"vacancyId": 2}]
        client.fetch_full.return_value = {
            "url": "https://hh.ru/vacancy/2",
            "name": "Инженер",
            "employer": "Компания",
        }
        hh_module = SimpleNamespace(HHClient=MagicMock(return_value=client))
        with (
            patch.dict("sys.modules", {"src.collectors.hh_client": hh_module}),
            patch("src.collectors.pipeline.VacancyStorage") as factory,
            patch("src.collectors.pipeline.datetime") as clock,
        ):
            storage = factory.return_value.__enter__.return_value
            storage.exists.side_effect = [True, False]
            storage.add_vacancy.return_value = True
            clock.now.return_value = CHECKED_AT
            self.assertEqual(collect_hh(1, "query"), (1, 0, 2))
            client.fetch_full.assert_called_once_with({"vacancyId": 2})
            data = storage.add_vacancy.call_args.args[0]
            self.assertEqual(data["status"], "active")
            self.assertEqual(data["last_checked_at"], CHECKED_AT)
            storage.update_vacancy_status.assert_not_called()
            client.session.get.assert_not_called()

    def test_serper_new_active_with_page_time_and_duplicate_skipped(self) -> None:
        """Дата берётся после загрузки, до извлечения LLM; дубликат не скрейпится."""
        with (
            patch("src.collectors.pipeline.SerperClient") as client_factory,
            patch("src.collectors.pipeline.VacancyStorage") as storage_factory,
            patch(
                "src.collectors.pipeline.scrape", return_value="Текст вакансии"
            ) as scrape,
            patch(
                "src.collectors.pipeline.extract_vacancy",
                return_value={"url": "new", "name": "Инженер", "company": "Компания"},
            ),
            patch("src.collectors.pipeline.datetime") as clock,
        ):
            client_factory.return_value.search.return_value = [
                {"link": "existing"},
                {"link": "new"},
            ]
            storage = storage_factory.return_value.__enter__.return_value
            storage.exists.side_effect = [True, False]
            storage.add_vacancy.return_value = True
            clock.now.return_value = CHECKED_AT
            self.assertEqual(collect_serper(1, "query", MagicMock()), (1, 0, 2))
            scrape.assert_called_once_with("new")
            data = storage.add_vacancy.call_args.args[0]
            self.assertEqual(data["status"], "active")
            self.assertEqual(data["last_checked_at"], CHECKED_AT)
            self.assertEqual(data["employer"], "Компания")
            storage.update_vacancy_status.assert_not_called()

    def test_failed_hh_detail_does_not_create_active_record(self) -> None:
        """Неудачная загрузка деталей не приводит к сохранению active."""
        client = MagicMock()
        client.search.side_effect = [[{"vacancyId": 1}], []]
        client.fetch_full.return_value = None
        hh_module = SimpleNamespace(HHClient=MagicMock(return_value=client))
        with (
            patch.dict("sys.modules", {"src.collectors.hh_client": hh_module}),
            patch("src.collectors.pipeline.VacancyStorage") as factory,
        ):
            storage = factory.return_value.__enter__.return_value
            storage.exists.return_value = False
            self.assertEqual(collect_hh(1, "query"), (0, 0, 1))
            storage.add_vacancy.assert_not_called()

    def test_serper_failed_download_or_extraction_does_not_insert(self) -> None:
        """Ошибка доступа, архив или ошибка извлечения не создают запись."""
        for text, expected_errors in (("", 1), ("Текст", 0)):
            with (
                self.subTest(text=text),
                patch("src.collectors.pipeline.SerperClient") as client_factory,
                patch("src.collectors.pipeline.VacancyStorage") as factory,
                patch("src.collectors.pipeline.scrape", return_value=text),
                patch(
                    "src.collectors.pipeline.extract_vacancy", return_value=None
                ) as extract,
            ):
                client_factory.return_value.search.side_effect = [[{"link": "new"}], []]
                storage = factory.return_value.__enter__.return_value
                storage.exists.return_value = False
                self.assertEqual(
                    collect_serper(1, "query", MagicMock()), (0, expected_errors, 1)
                )
                storage.add_vacancy.assert_not_called()
                if not text:
                    extract.assert_not_called()
