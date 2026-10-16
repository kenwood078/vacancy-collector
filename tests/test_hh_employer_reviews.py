"""Извлечение рейтинга HH без cookies пользователя, сети и БД."""

import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

# Отдельный экземпляр модуля не подменяет cookies в настоящем HHClient.
_SPEC = importlib.util.spec_from_file_location(
    "_hh_reviews_test_client",
    Path(__file__).resolve().parents[1] / "src/collectors/hh_client.py",
)
_HH = importlib.util.module_from_spec(_SPEC)
with patch.dict(os.environ, {"HH_TOKEN": "test-token", "HH_XSRF": "test-xsrf"}):
    _SPEC.loader.exec_module(_HH)


def _vacancy(vacancy_id: int = 1, employer_id: int = 7) -> dict:
    """Создаёт минимальную поисковую карточку.

    Args:
        vacancy_id: ID вакансии.
        employer_id: ID работодателя.

    Returns:
        Карточка HH без рейтинга.
    """
    return {
        "vacancyId": vacancy_id,
        "name": "Инженер",
        "company": {"id": employer_id, "name": "Компания"},
    }


def _detail_response(
    vacancy_id: int = 1, employer_id: int = 7, widget: bool = True
) -> requests.Response:
    """Создаёт успешный ответ страницы с реальным расположением полей.

    Args:
        vacancy_id: ID вакансии.
        employer_id: ID работодателя.
        widget: включить ли URL блока рейтинга.

    Returns:
        HTTP-ответ с минимальным HH-Lux-InitialState.
    """
    state = {
        "vacancyView": {
            "vacancyFull": {
                "description": "<p>Описание вакансии</p>",
                "keySkills": {"keySkill": ["BGP"]},
            }
        }
    }
    if widget:
        state["microFrontends"] = {
            "employerReviewsSmall": {
                "url": (
                    "/employer_reviews/proxy_components/small_widget"
                    f"?employerId={employer_id}&vacancyId={vacancy_id}&is_magritte=true"
                )
            }
        }
    response = requests.Response()
    response.status_code = 200
    response.encoding = "utf-8"
    response._content = (
        '<template id="HH-Lux-InitialState">' + json.dumps(state) + "</template>"
    ).encode()
    return response


def _reviews_response(payload: object, code: int = 200) -> requests.Response:
    """Создаёт ответ виджета с заданным JSON.

    Args:
        payload: содержимое JSON-ответа.
        code: HTTP-код.

    Returns:
        HTTP-ответ виджета.
    """
    response = requests.Response()
    response.status_code = code
    response._content = json.dumps(payload).encode()
    return response


class EmployerReviewsTests(unittest.TestCase):
    """Известные источники рейтинга и ограничение дополнительных запросов."""

    def setUp(self) -> None:
        """Создаёт клиент с тестовыми cookies и подменяет сеть и паузы."""
        self.client = _HH.HHClient()
        self.addCleanup(self.client.session.close)
        self.client.session = MagicMock(spec=requests.Session)
        sleep = patch.object(_HH.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_search_rating_has_priority_and_no_extra_request(self) -> None:
        """Доступный рейтинг из выдачи не требует запроса виджета."""
        vacancy = _vacancy()
        vacancy["company"]["employerReviews"] = {
            "totalRating": "4.2",
            "reviewsCount": 1661,
        }
        self.client.session.get.return_value = _detail_response()
        result = self.client.fetch_full(vacancy)
        self.assertEqual(result["employer_rating"], 4.2)
        self.assertEqual(result["employer_reviews_count"], 1661)
        self.client.session.get.assert_called_once_with(
            "https://hh.ru/vacancy/1", timeout=20
        )
        self.assertEqual(
            result["requirements"], "Описание вакансии\n\nКлючевые навыки: BGP"
        )

    def test_missing_rating_uses_widget_with_cookie_session_and_headers(self) -> None:
        """Резервный запрос извлекает оба существующих поля БД."""
        self.client.session.get.side_effect = [
            _detail_response(),
            _reviews_response(
                {"employerReviews": {"totalRating": "4.2", "reviewsCount": 1661}}
            ),
        ]
        result = self.client.fetch_full(_vacancy())
        self.assertEqual(result["employer_rating"], 4.2)
        self.assertEqual(result["employer_reviews_count"], 1661)
        self.assertEqual(self.client.session.get.call_count, 2)
        call = self.client.session.get.call_args
        self.assertIn("employerId=7", call.args[0])
        self.assertEqual(
            call.kwargs,
            {
                "timeout": 20,
                "headers": {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                    "Referer": "https://hh.ru/vacancy/1",
                },
            },
        )
        self.assertEqual(
            [call.args for call in self.sleep.call_args_list], [(1.5,), (1.5,)]
        )

    def test_widget_result_reused_for_same_employer(self) -> None:
        """Две новые вакансии компании требуют только один запрос рейтинга."""
        self.client.session.get.side_effect = [
            _detail_response(),
            _reviews_response(
                {"employerReviews": {"totalRating": 4.5, "reviewsCount": 20}}
            ),
            _detail_response(vacancy_id=2),
        ]
        first = self.client.fetch_full(_vacancy())
        second = self.client.fetch_full(_vacancy(vacancy_id=2))
        self.assertEqual(first["employer_rating"], second["employer_rating"])
        self.assertEqual(second["employer_reviews_count"], 20)
        self.assertEqual(self.client.session.get.call_count, 3)

    def test_invalid_search_rating_uses_widget_and_preserves_known_count(self) -> None:
        """Резервный рейтинг не затирает корректное число отзывов из выдачи."""
        vacancy = _vacancy()
        vacancy["company"]["employerReviews"] = {
            "totalRating": "bad",
            "reviewsCount": 20,
        }
        self.client.session.get.side_effect = [
            _detail_response(),
            _reviews_response({"employerReviews": {"totalRating": "4.2"}}),
        ]
        result = self.client.fetch_full(vacancy)
        self.assertEqual(result["employer_rating"], 4.2)
        self.assertEqual(result["employer_reviews_count"], 20)
        self.assertEqual(self.client.session.get.call_count, 2)

    def test_search_result_populates_cache_but_fresh_search_has_priority(self) -> None:
        """Кэш помогает пропускам, а новое значение выдачи имеет приоритет."""
        self.client.session.get.side_effect = [
            _detail_response(),
            _detail_response(2),
            _detail_response(3),
        ]
        first = _vacancy()
        first["company"]["employerReviews"] = {"totalRating": "4.2", "reviewsCount": 10}
        self.client.fetch_full(first)
        cached = self.client.fetch_full(_vacancy(2))
        self.assertEqual(cached["employer_rating"], 4.2)
        third = _vacancy(3)
        third["company"]["employerReviews"] = {"totalRating": "4.3", "reviewsCount": 11}
        self.assertEqual(self.client.fetch_full(third)["employer_rating"], 4.3)
        self.assertEqual(self.client.session.get.call_count, 3)

    def test_different_employers_do_not_share_rating(self) -> None:
        """Совпадающее название компаний не смешивает разные ID."""
        self.client.session.get.side_effect = [
            _detail_response(),
            _reviews_response({"employerReviews": {"totalRating": "4.2"}}),
            _detail_response(2, employer_id=8),
            _reviews_response({"employerReviews": {"totalRating": "3.5"}}),
        ]
        self.assertEqual(self.client.fetch_full(_vacancy())["employer_rating"], 4.2)
        self.assertEqual(
            self.client.fetch_full(_vacancy(2, employer_id=8))["employer_rating"], 3.5
        )
        self.assertEqual(self.client.session.get.call_count, 4)

    def test_failed_widget_is_cached_and_does_not_discard_vacancy(self) -> None:
        """Timeout не прерывает сбор и не повторяется для той же компании."""
        self.client.session.get.side_effect = [
            _detail_response(),
            requests.Timeout("timeout"),
            _detail_response(2),
        ]
        for vacancy in (_vacancy(), _vacancy(2)):
            result = self.client.fetch_full(vacancy)
            self.assertEqual(result["name"], "Инженер")
            self.assertIsNone(result["employer_rating"])
        self.assertEqual(self.client.session.get.call_count, 3)

    def test_invalid_widget_responses_do_not_discard_vacancy(self) -> None:
        """HTTP-ошибка, плохой JSON и неизвестная схема оставляют поля пустыми."""
        broken = requests.Response()
        broken.status_code = 200
        broken._content = b"<html>not JSON</html>"
        for response in (
            _reviews_response({}, 403),
            broken,
            _reviews_response([]),
            _reviews_response({"employerReviews": []}),
        ):
            with self.subTest(response=response):
                self.client._employer_reviews_cache.clear()
                self.client.session.get.side_effect = [_detail_response(), response]
                result = self.client.fetch_full(_vacancy())
                self.assertEqual(result["employer"], "Компания")
                self.assertIsNone(result["employer_rating"])
                self.assertIsNone(result["employer_reviews_count"])

    def test_missing_url_does_not_poison_cache_for_later_vacancy(self) -> None:
        """Следующая страница может предоставить URL, отсутствовавший на первой."""
        self.client.session.get.side_effect = [
            _detail_response(widget=False),
            _detail_response(2),
            _reviews_response({"employerReviews": {"totalRating": "4.2"}}),
        ]
        self.assertIsNone(self.client.fetch_full(_vacancy())["employer_rating"])
        self.assertEqual(self.client.fetch_full(_vacancy(2))["employer_rating"], 4.2)

    def test_widget_must_belong_to_same_employer_and_hh(self) -> None:
        """Чужой работодатель или сторонний URL не используется как источник."""
        for url in (
            "https://[invalid",
            "https://example.com/employer_reviews/proxy_components/small_widget?employerId=7",
            "/employer_reviews/proxy_components/small_widget?employerId=8",
            "/other?employerId=7",
        ):
            with (
                self.subTest(url=url),
                patch.object(
                    self.client,
                    "_get_detail",
                    return_value={
                        "requirements_text": "Текст",
                        "employer_reviews_url": url,
                    },
                ),
            ):
                result = self.client.fetch_full(_vacancy())
                self.assertIsNone(result["employer_rating"])
        self.client.session.get.assert_not_called()

    def test_zero_values_and_independent_fields(self) -> None:
        """Нули сохраняются; плохое поле не портит второе корректное поле."""
        cases = [
            ({"totalRating": "0", "reviewsCount": 0}, (0.0, 0)),
            ({"totalRating": "4.2", "reviewsCount": None}, (4.2, None)),
            ({"totalRating": None, "reviewsCount": "12"}, (None, 12)),
            ({"totalRating": "NaN", "reviewsCount": 5}, (None, 5)),
            ({"totalRating": "inf", "reviewsCount": -1}, (None, None)),
            ({"totalRating": True, "reviewsCount": True}, (None, None)),
            ({"totalRating": 6, "reviewsCount": 2.5}, (None, None)),
            ({"totalRating": "bad", "reviewsCount": "bad"}, (None, None)),
            (None, (None, None)),
        ]
        for reviews, expected in cases:
            with self.subTest(reviews=reviews):
                self.assertEqual(_HH._parse_employer_reviews(reviews), expected)
        vacancy = _vacancy()
        vacancy["company"]["employerReviews"] = {"totalRating": "0", "reviewsCount": 0}
        self.client.session.get.return_value = _detail_response()
        result = self.client.fetch_full(vacancy)
        self.assertEqual(result["employer_rating"], 0.0)
        self.assertEqual(self.client.session.get.call_count, 1)

    def test_missing_detail_still_skips_vacancy(self) -> None:
        """Рейтинг не запрашивается, если основная страница недоступна."""
        self.client.session.get.return_value = _reviews_response({}, 500)
        self.assertIsNone(self.client.fetch_full(_vacancy()))
        self.assertEqual(self.client.session.get.call_count, 1)
