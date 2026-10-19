"""Проверки условий подбора без БД, LLM и запросов к HH."""

import unittest
from unittest.mock import MagicMock

from src.analytics.resume_extractor import ResumeExtractor
from src.matching.filters import matches_salary, matches_work_location
from src.storage import VacancyStorage


class ResumeExperienceTests(unittest.TestCase):
    """Известный нулевой стаж отличается от отсутствующих данных."""

    def test_year_normalization(self) -> None:
        """Ноль и положительный стаж валидны; bool и отрицательный стаж нет."""
        for value, expected in (
            (0, 0),
            (0.0, 0),
            (2.5, 2),
            (7, 7),
            (None, None),
            (-1, None),
            (True, None),
            (False, None),
            ("0", None),
        ):
            with self.subTest(value=value):
                self.assertEqual(ResumeExtractor._to_year(value), expected)

    def test_stated_zero_takes_precedence_over_calculated(self) -> None:
        """При выборе источника ноль не заменяется вычисленным стажем."""
        for stated, calculated, expected in (
            (0, 8, 0),
            (0, None, 0),
            (None, 0, 0),
            (None, 4, 4),
            (None, None, None),
            (5, 8, 5),
        ):
            with self.subTest(stated=stated, calculated=calculated):
                result = ResumeExtractor._validate(
                    {
                        "experience_years_stated": stated,
                        "experience_years_calculated": calculated,
                    }
                )
                self.assertEqual(result["experience_years"], expected)

    def test_experience_categories_preserved(self) -> None:
        """Правила допустимых категорий HH остаются прежними."""
        for years, expected in (
            (None, None),
            (0, ["noExperience", "between1And3"]),
            (2, ["noExperience", "between1And3"]),
            (3, ["between1And3", "between3And6"]),
            (5, ["between1And3", "between3And6"]),
            (6, ["between3And6", "moreThan6"]),
            (10, ["between3And6", "moreThan6"]),
        ):
            with self.subTest(years=years):
                self.assertEqual(VacancyStorage._allowed_experience(years), expected)


class WorkLocationTests(unittest.TestCase):
    """Есть хотя бы один общий формат, допустимый по городу и переезду."""

    def test_formats_and_location(self) -> None:
        """Все сочетания удалёнки, офиса и гибрида проверяют общий вариант."""
        for formats, relocate, vacancy_formats, city, expected in (
            ("ON_SITE", False, "ON_SITE", "Казань", True),
            ("ON_SITE", False, "ON_SITE", "Москва", False),
            ("REMOTE", False, "ON_SITE", "Казань", False),
            ("REMOTE", False, "REMOTE", "Москва", True),
            ("REMOTE,HYBRID", False, "ON_SITE", "Казань", False),
            ("REMOTE,HYBRID", False, "HYBRID", "Казань", True),
            ("REMOTE,HYBRID", False, "HYBRID", "Москва", False),
            ("REMOTE,HYBRID", False, "REMOTE,ON_SITE", "Москва", True),
            ("REMOTE,HYBRID,ON_SITE", False, "ON_SITE", "Казань", True),
            ("REMOTE,HYBRID,ON_SITE", False, "HYBRID", "Москва", False),
            ("ON_SITE", True, "ON_SITE", "Москва", True),
            ("ON_SITE", True, "REMOTE", "Москва", False),
            ("REMOTE,HYBRID", True, "HYBRID", "Москва", True),
            ("REMOTE,HYBRID", True, "ON_SITE", "Москва", False),
            ("ON_SITE", False, "REMOTE,ON_SITE", "Москва", False),
            ("HYBRID", False, "REMOTE,HYBRID", "Москва", False),
            (" remote , hybrid ", False, " Hybrid , REMOTE ", "Москва", True),
        ):
            with self.subTest(
                formats=formats, relocate=relocate, vacancy=vacancy_formats, city=city
            ):
                self.assertEqual(
                    matches_work_location(
                        {
                            "work_format": formats,
                            "city": "Казань",
                            "ready_to_relocate": relocate,
                        },
                        {"work_format": vacancy_formats, "city": city},
                    ),
                    expected,
                )

    def test_unknown_format_and_city(self) -> None:
        """Неизвестное поле само по себе не означает несовместимость."""
        for unknown in (None, "", " ", "unknown", " UnKnOwN "):
            with self.subTest(unknown=unknown):
                self.assertTrue(
                    matches_work_location(
                        {"work_format": unknown}, {"work_format": "ON_SITE"}
                    )
                )
                self.assertTrue(
                    matches_work_location(
                        {"work_format": "ON_SITE", "city": "Казань"},
                        {"work_format": unknown, "city": "Казань"},
                    )
                )
                self.assertTrue(
                    matches_work_location(
                        {"work_format": "HYBRID", "city": "Казань"},
                        {"work_format": "HYBRID", "city": unknown},
                    )
                )
                self.assertTrue(
                    matches_work_location(
                        {"work_format": "ON_SITE", "city": unknown},
                        {"work_format": "ON_SITE", "city": "Москва"},
                    )
                )
                self.assertTrue(
                    matches_work_location(
                        {"work_format": "REMOTE", "city": "Казань"},
                        {"work_format": unknown, "city": "Москва"},
                    )
                )
        self.assertFalse(
            matches_work_location(
                {"work_format": "REMOTE,unknown", "city": "Казань"},
                {"work_format": "ON_SITE", "city": "Казань"},
            )
        )

    def test_city_normalization(self) -> None:
        """Регистр и повторные пробелы не создают разные города."""
        self.assertTrue(
            matches_work_location(
                {"work_format": "ON_SITE", "city": " Нижний   Новгород "},
                {"work_format": "ON_SITE", "city": "нижний новгород"},
            )
        )


class FilteredRetrievalTests(unittest.TestCase):
    """Python-фильтры не ограничиваются первой SQL-порцией."""

    def setUp(self) -> None:
        """Создаёт хранилище без соединения и DDL."""
        self.storage = object.__new__(VacancyStorage)
        self.storage.conn = MagicMock()
        self.cursor = self.storage.conn.cursor.return_value.__enter__.return_value

    def _set_candidates(self, rows: list[dict]) -> None:
        """Имитирует SQL-страницы с ограничением и продолжением по позиции.

        Args:
            rows: кандидаты с ID, score и необязательным точным расстоянием.
        """
        self.cursor.reset_mock()
        self.candidates = [
            dict(
                row,
                _match_distance=row.get("_match_distance", 1 - row.get("score", 0)),
            )
            for row in rows
        ]

        def execute(query: str, params: list) -> None:
            """Выдаёт только следующую ограниченную порцию SQL-результата."""
            self.assertIn("LIMIT %s", query)
            self.assertNotIn("OFFSET", query)
            self.assertEqual(query.count("%s"), len(params))
            self.assertEqual(params[-1], 100)
            # Ограничение в имитации также прерывает ошибочное зацикливание.
            self.assertLessEqual(self.cursor.execute.call_count, 10)
            eligible = sorted(
                self.candidates, key=lambda row: (row["_match_distance"], row["id"])
            )
            if "> (%s, %s)" in query:
                after = tuple(params[-4:-2])
                eligible = [
                    row
                    for row in eligible
                    if (row["_match_distance"], row["id"]) > after
                ]
            self.cursor.fetchall.return_value = [
                dict(row) for row in eligible[: params[-1]]
            ]

        self.cursor.execute.side_effect = execute

    def test_refill_beyond_first_batch(self) -> None:
        """Две сотни офисных вакансий не скрывают удалёнку ниже в рейтинге."""
        rejected = [
            {"id": i, "work_format": "ON_SITE", "score": 0.99 - i / 1000}
            for i in range(200)
        ]
        accepted = [
            {"id": 200 + i, "work_format": "REMOTE", "score": 0.7 - i / 100}
            for i in range(3)
        ]
        self._set_candidates(rejected + accepted)
        result = self.storage.find_top_vacancies(
            [0.1], {"work_format": "REMOTE,HYBRID"}, top_n=2
        )
        self.assertEqual(result, accepted[:2])
        self.assertEqual(self.cursor.execute.call_count, 3)
        self.cursor.fetchmany.assert_not_called()
        query, params = self.cursor.execute.call_args.args
        self.assertIn("ORDER BY a.embedding <=> %s::vector, v.id", query)
        self.assertIn("((a.embedding <=> %s::vector), v.id) > (%s, %s)", query)
        self.assertEqual(params[-4:-2], [1 - rejected[-1]["score"], 199])

    def test_exhaustion_returns_partial_or_empty_top(self) -> None:
        """Исчерпание не зацикливает добор и сохраняет порядок результатов."""
        accepted = {"id": 2, "work_format": "REMOTE", "score": 0.7}
        for rows, expected in (
            ([], []),
            ([{"id": 1, "work_format": "ON_SITE", "score": 0.9}], []),
            ([{"id": 1, "work_format": "ON_SITE", "score": 0.9}, accepted], [accepted]),
        ):
            with self.subTest(rows=rows):
                self._set_candidates(rows)
                self.assertEqual(
                    self.storage.find_top_vacancies(
                        [0.1], {"work_format": "REMOTE"}, top_n=3
                    ),
                    expected,
                )
                self.assertEqual(self.cursor.execute.call_count, 1)

    def test_exact_full_page_exhaustion(self) -> None:
        """Полная отсеянная страница требует одного запроса для проверки конца."""
        self._set_candidates(
            [{"id": i, "work_format": "ON_SITE", "score": 0.9} for i in range(100)]
        )
        self.assertEqual(
            self.storage.find_top_vacancies([0.1], {"work_format": "REMOTE"}), []
        )
        self.assertEqual(self.cursor.execute.call_count, 2)

    def test_stops_after_first_sufficient_page(self) -> None:
        """При достаточной первой порции остальные строки не загружаются."""
        rows = [{"id": i, "score": 0.9} for i in range(500)]
        self._set_candidates(rows)
        self.assertEqual(
            self.storage.find_top_vacancies([0.1], {}, top_n=20), rows[:20]
        )
        self.assertEqual(self.cursor.execute.call_count, 1)
        self.assertEqual(len(self.cursor.fetchall.return_value), 100)

    def test_equal_distances_cross_page_boundaries_without_duplicates(self) -> None:
        """При одинаковых расстояниях ID предотвращает пропуски и дубли."""
        rows = [
            {
                "id": i,
                "score": 0.8,
                "_match_distance": 0.2,
                "work_format": "ON_SITE" if i < 198 else "REMOTE",
            }
            for i in range(1, 203)
        ]
        self._set_candidates(list(reversed(rows)))
        result = self.storage.find_top_vacancies(
            [0.1], {"work_format": "REMOTE"}, top_n=5
        )
        self.assertEqual([row["id"] for row in result], [198, 199, 200, 201, 202])
        self.assertTrue(all("_match_distance" not in row for row in result))
        calls = self.cursor.execute.call_args_list
        self.assertEqual(calls[1].args[1][-4:-2], [0.2, 100])
        self.assertEqual(calls[2].args[1][-4:-2], [0.2, 200])

    def test_cursor_uses_unrounded_distance(self) -> None:
        """Разный точный косинус с одинаковым score не теряется на границе."""
        rows = [
            {
                "id": i,
                "score": 0.9,
                "_match_distance": 0.100000001,
                "work_format": "ON_SITE",
            }
            for i in range(101, 201)
        ] + [
            {
                "id": i,
                "score": 0.9,
                "_match_distance": 0.100000002,
                "work_format": "REMOTE",
            }
            for i in range(1, 6)
        ]
        self._set_candidates(rows)
        result = self.storage.find_top_vacancies(
            [0.1], {"work_format": "REMOTE"}, top_n=5
        )
        self.assertEqual([row["id"] for row in result], [1, 2, 3, 4, 5])
        self.assertEqual(
            self.cursor.execute.call_args.args[1][-4:-2], [0.100000001, 200]
        )

    def test_removed_boundary_row_does_not_shift_next_page(self) -> None:
        """Удаление последней строки страницы не сдвигает позицию следующей."""
        self._set_candidates(
            [
                {
                    "id": i,
                    "score": 0.8,
                    "work_format": "ON_SITE" if i <= 100 else "REMOTE",
                }
                for i in range(1, 104)
            ]
        )
        page_execute = self.cursor.execute.side_effect

        def execute(query: str, params: list) -> None:
            """Удаляет строку границы после получения первой страницы."""
            if self.cursor.execute.call_count == 2:
                self.candidates = [row for row in self.candidates if row["id"] != 100]
            page_execute(query, params)

        self.cursor.execute.side_effect = execute
        result = self.storage.find_top_vacancies(
            [0.1], {"work_format": "REMOTE"}, top_n=3
        )
        self.assertEqual([row["id"] for row in result], [101, 102, 103])

    def test_salary_filter_refills_and_preserves_score(self) -> None:
        """Недостаточные месячные суммы не скрывают другие валюты и периоды."""
        rows = [
            {
                "id": 100 + i,
                "score": 0.8 - i / 100,
                "salary_to": salary,
                "salary_currency": currency,
                "salary": text,
            }
            for i, (salary, currency, text) in enumerate(
                (
                    (50_000, "RUR", "до 50000 ₽ в месяц"),
                    (2_000, "USD", "до 2000 USD в месяц"),
                    (1_000, "RUR", "до 1000 ₽ в час"),
                    (200_000, "RUR", "до 200000 ₽ в месяц"),
                )
            )
        ]
        rejected = [dict(rows[0], id=i, score=0.99 - i / 1000) for i in range(100)]
        self._set_candidates(rejected + rows[1:])
        result = self.storage.find_top_vacancies(
            [0.1], {"salary_min": 100_000, "salary_expectation": "100000 ₽"}, top_n=3
        )
        self.assertEqual(result, rows[1:])
        self.assertEqual(self.cursor.execute.call_count, 2)


class SalaryFilterTests(unittest.TestCase):
    """Сравниваются только известные валюты и месячные суммы."""

    def setUp(self) -> None:
        """Создаёт сопоставимую месячную зарплату ниже ожиданий."""
        self.resume = {"salary_min": 200_000, "salary_expectation": "от 200000 ₽"}
        self.vacancy = {
            "salary_to": 180_000,
            "salary_currency": "RUR",
            "salary": "до 180000 ₽ в месяц (на руки)",
        }

    def test_monthly_salary_bounds(self) -> None:
        """Недостаточный максимум исключается; равенство и открытая вилка нет."""
        for salary, expected in ((180_000, False), (200_000, True), (250_000, True)):
            with self.subTest(salary=salary):
                self.assertEqual(
                    matches_salary(self.resume, dict(self.vacancy, salary_to=salary)),
                    expected,
                )
        self.assertTrue(matches_salary(self.resume, dict(self.vacancy, salary_to=None)))
        self.assertTrue(matches_salary({}, self.vacancy))
        self.assertTrue(matches_salary(self.resume, {}))

    def test_currency_aliases_and_codes(self) -> None:
        """Рубли и явные коды сравниваются без курсов и предположений."""
        for expectation, currency in (
            ("от 200000 ₽", "RUR"),
            ("от 200000 руб.", "RUB"),
            ("от 200000 рублей", "RUR"),
            ("от 200000 рубля", "RUB"),
            ("от 200000 RUR", "RUB"),
            ("от 200000 rub", " rur "),
            ("от 200000 USD", "USD"),
            ("от $200000", "USD"),
            ("от 200000 долларов", "USD"),
            ("от 200000 €", "EUR"),
            ("от 200000 евро", "EUR"),
            ("от 200000 eur", "EUR"),
            ("от 200000 KZT", "KZT"),
            ("от 200000 ₸", "KZT"),
            ("от 200000 BYN", "BYN"),
            ("от 200000 GBP", "GBP"),
        ):
            with self.subTest(expectation=expectation, currency=currency):
                self.assertFalse(
                    matches_salary(
                        dict(self.resume, salary_expectation=expectation),
                        dict(self.vacancy, salary_currency=currency),
                    )
                )

    def test_unknown_different_or_ambiguous_currency_not_compared(self) -> None:
        """Пропущенные и неоднозначные валюты не превращаются в рубли."""
        for expectation, currency in (
            ("200000 ₽", "USD"),
            ("200000 USD", "RUR"),
            ("200000 EUR", "USD"),
            ("200000", "RUR"),
            (None, "RUR"),
            ("200000 ₽", None),
            ("200000 ₽", ""),
            ("200000 ₽", "unknown"),
            ("200000 ₽ / USD", "RUR"),
            ("200000 RUB или EUR", "EUR"),
            ("200000 CAD$", "USD"),
            ("200000 CAD $", "CAD"),
            ("200000 XXX", "XXX"),
        ):
            with self.subTest(expectation=expectation, currency=currency):
                self.assertTrue(
                    matches_salary(
                        dict(self.resume, salary_expectation=expectation),
                        dict(self.vacancy, salary_currency=currency),
                    )
                )

    def test_non_monthly_salary_not_compared(self) -> None:
        """Немесячные суммы с любой стороны не переводятся в месячные."""
        for period in (
            "в час",
            "за смену",
            "за вахту",
            "за услугу",
            "в день",
            "в сутки",
            "в год",
            "за неделю",
            "за проект",
            "/ч",
            "руб./час",
            "per hour",
            "per shift",
            "per year",
        ):
            with self.subTest(period=period):
                self.assertTrue(
                    matches_salary(
                        self.resume, dict(self.vacancy, salary=f"180000 ₽ {period}")
                    )
                )
                self.assertTrue(
                    matches_salary(
                        dict(self.resume, salary_expectation=f"200000 ₽ {period}"),
                        self.vacancy,
                    )
                )
        for salary in (None, "", "до 180000 ₽"):
            with self.subTest(salary=salary):
                self.assertTrue(
                    matches_salary(self.resume, dict(self.vacancy, salary=salary))
                )

    def test_monthly_period_spellings(self) -> None:
        """Месяц распознаётся в сохранённых строках без обработки налогов."""
        for period in ("в месяц", "за месяц", "/мес.", "per month", "monthly"):
            with self.subTest(period=period):
                self.assertFalse(
                    matches_salary(
                        dict(self.resume, salary_expectation=f"200000 ₽ {period}"),
                        dict(self.vacancy, salary=f"180000 ₽ {period} (до вычета)"),
                    )
                )
