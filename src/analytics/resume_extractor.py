import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ._extraction_utils import _clean_item, _clean_json_response, _clean_list

if TYPE_CHECKING:
    from crewai import LLM

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

ALLOWED_ENGLISH = {"A1", "A2", "B1", "B2", "C1", "C2", "native", "unknown"}
ALLOWED_WORK_FORMAT = {"REMOTE", "HYBRID", "ON_SITE", "unknown"}

LIMITS = {
    "stack": 35,
    "tasks": 15,
    "certifications": 10,
    "domains": 5,
    "programming_languages": 10,
}

PROMPT_TEMPLATE = """Ты — парсер резюме. Извлекаешь данные в JSON.

ФОРМАТ ОТВЕТА — все ключи обязательны:
{{
  "role": "Сетевой инженер",
  "city": "Москва",
  "work_format": "REMOTE|HYBRID|ON_SITE|unknown",
  "experience_years_stated": 8,
  "experience_years_calculated": null,
  "salary_expectation": "от 220 000 ₽",
  "ready_to_relocate": false,
  "stack": ["string"],
  "tasks": ["string"],
  "certifications": ["string"],
  "domains": ["string"],
  "programming_languages": ["string"],
  "english_level": "A1|A2|B1|B2|C1|C2|native|unknown"
}}

ЖЁСТКИЕ ПРАВИЛА:
1. Только JSON. Без markdown.
2. Пустой список — []. Пустое число — null.
3. Бери ТОЛЬКО из текста. Не выдумывай.

ПОЛЕ role — желаемая должность одной строкой.
- Бери из шапки («Желаемая должность», «Специализация») или из последней/текущей позиции опыта.
- Если явно не указана — null.

ПОЛЕ city — город проживания. Одна строка. Не указан — "unknown".

ПОЛЕ work_format — формат работы, строка из одного или нескольких значений через запятую.
Возможные значения: REMOTE, HYBRID, ON_SITE.
- «удалённо» → "REMOTE"
- «гибрид», «частично удалённо» → "HYBRID"
- «офис» → "ON_SITE"
- «удалённо или гибрид» → "REMOTE,HYBRID"
- «не имеет значения» → "REMOTE,HYBRID,ON_SITE"
- «готов к переезду» → работа не привязана к городу, добавь ON_SITE и HYBRID
- «готов к удалённой работе» → добавь REMOTE
- Не указан → "unknown"

ПОЛЕ experience_years_stated — общий стаж из шапки.
- Ищи «Стаж: X лет», «Опыт работы — X лет», «X лет опыта».
- Целое число лет. Не указан — null.
- НЕ считай по датам, только копируй число из текста.

ПОЛЕ experience_years_calculated — стаж по датам работ.
- Считай ТОЛЬКО если stated = null.
- НЕ суммируй пересекающиеся периоды. Если работал на двух позициях одновременно — считай период один раз.
- Целое число лет, округли ВНИЗ.
- Данных нет — null.

ПОЛЕ salary_expectation — зарплатные ожидания как в тексте. Не указано — null.

ПОЛЕ ready_to_relocate — true/false.
- «готов к переезду» → true.
- «готов к командировкам», «готов к редким командировкам» → false (это не переезд).
- Не указано → false.

ПОЛЕ stack — технологии, протоколы, вендоры, ОС, инструменты.
- Приоритет: сначала ключевые для роли (протоколы, вендоры, ОС, языки).
- Инструменты документации (Visio, Draw.io) — в конце.
- Канонично: "Cisco", а не "Cisco Catalyst 9300".
- До 35 пунктов.

ПОЛЕ tasks — что человек делал.
- Один пункт = одно действие, до 12 слов.
- Глагол в начале: "администрировал", "проектировал", "автоматизировал".
- До 15 пунктов.

ПОЛЕ certifications — только сертификаты (CCNA, CCNP, HCIA, IELTS, CKA).

ПОЛЕ domains — отрасль, в которой человек работал. НЕ профессия, НЕ навык.
Хорошо: ЦОД, телеком, банк, финтех, DPI, NGFW, облачные провайдеры, операторы связи.
Плохо (запрещено): "Сетевая инженерия", "Сетевые сети", "IT", "Автоматизация",
"Кибербезопасность" (если человек просто интересуется — не считается),
навыки (Linux, Python), инструменты (Ansible, Zabbix).
1–5 штук. Если человек нигде не работал — верни [].

ПОЛЕ programming_languages — только языки (Python, Go, Java, C++, SQL, Bash).

ПОЛЕ english_level — одно из: A1, A2, B1, B2, C1, C2, native, unknown.
- «В1 — Средний» → "B1".
- «Upper-Intermediate» → "B2".
- Не указан → "unknown".

Текст резюме:
<<<
{resume_text}
>>>

Верни только JSON.
"""


class ResumeExtractor:
    """Извлекает структурированные данные из резюме через LLM."""

    def __init__(self, llm: "LLM") -> None:
        """Сохраняет LLM и имя модели для извлечения полей.

        Args:
            llm: экземпляр CrewAI LLM с методом call(prompt).
        """
        self.llm = llm
        self.llm_model = getattr(llm, "model", "unknown")

    def extract(self, text: str) -> dict | None:
        """Извлекает и нормализует поля резюме через LLM.

        Args:
            text: исходный текст резюме.

        Returns:
            Словарь с ролью, городом, форматом работы, стажем, зарплатными
            ожиданиями и их границами, готовностью к переезду, списками навыков,
            задач, сертификатов, доменов и языков, уровнем английского,
            llm_model и prompt_version. None для короткого текста или ошибки ответа.
        """
        if len(text) < 100:
            logger.info("Skip (too short): %d chars", len(text))
            return None

        prompt = PROMPT_TEMPLATE.format(resume_text=text[:10000])

        try:
            raw = self.llm.call(prompt)
            cleaned = _clean_json_response(raw)
            result = json.loads(cleaned)
        except Exception as e:  # noqa: BLE001 -- сохранить обработку всех ошибок операции
            logger.warning("Resume extract failed: %s", e)
            return None

        validated = self._validate(result)
        if validated is None:
            return None

        validated["llm_model"] = self.llm_model
        validated["prompt_version"] = PROMPT_VERSION
        return validated

    @staticmethod
    def _clean(item: str) -> str:
        """Очищает строку ответа LLM.

        Args:
            item: строка для очистки.

        Returns:
            Очищенная строка.
        """
        return _clean_item(item)

    @staticmethod
    def _to_list(value: Any, max_n: int) -> list[str]:
        """Преобразует значение JSON в ограниченный список строк.

        Args:
            value: значение для преобразования.
            max_n: максимальное число элементов результата.

        Returns:
            Очищенные непустые строки в исходном порядке.
        """
        return _clean_list(value, max_n, ResumeExtractor._clean)

    @staticmethod
    def _to_year(value: Any) -> int | None:
        """Приводит значение к целому году. Мусор → None.

        Args:
            value: значение для преобразования.

        Returns:
            Целое число лет или None для неподходящего значения.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        return None

    @staticmethod
    def _parse_salary(text: str | None) -> tuple[int | None, int | None]:
        """Парсит зарплату из строки.

        Args:
            text: исходный текст.

        Returns:
            Границы зарплаты; неизвестная граница представлена None.

        Examples:
            'от 220 000 ₽' → (220000, None)
            '200 000 - 300 000 ₽' → (200000, 300000)
            '3000 $' → (3000, 3000)
            'по договорённости' → (None, None)
        """
        if not text:
            return None, None

        # Склеиваем разряды: "220 000" → "220000", "1,500" → "1500"
        s = re.sub(r"(?<=\d)[\s,.](?=\d)", "", text)
        # Тире заменяем на пробел, чтобы числа разделились
        s = re.sub(r"[-–—]", " ", s)
        nums = [int(n) for n in re.findall(r"\d+", s)]

        if not nums:
            return None, None
        if len(nums) == 1:
            lower = text.lower()
            if "от" in lower:
                return nums[0], None
            if "до" in lower:
                return None, nums[0]
            return nums[0], nums[0]
        return nums[0], nums[-1]

    @staticmethod
    def _validate(result: dict) -> dict | None:
        """Нормализует структурированные поля ответа LLM.

        Args:
            result: разобранный ответ LLM.

        Returns:
            Нормализованный словарь или None, если ответ не является словарём.
        """
        if not isinstance(result, dict):
            return None

        role = result.get("role")
        role = ResumeExtractor._clean(str(role)) if role else None

        city = result.get("city")
        city = ResumeExtractor._clean(str(city)) if city else "unknown"

        wf_raw = str(result.get("work_format", "unknown")).strip().upper()
        wf_parts = [p.strip() for p in wf_raw.split(",") if p.strip()]
        wf_parts = [p for p in wf_parts if p in ALLOWED_WORK_FORMAT]
        if not wf_parts:
            wf = "unknown"
        else:
            wf = ",".join(dict.fromkeys(wf_parts))

        years = ResumeExtractor._to_year(
            result.get("experience_years_stated")
        ) or ResumeExtractor._to_year(result.get("experience_years_calculated"))

        salary_text = result.get("salary_expectation")
        salary_text = str(salary_text).strip() if salary_text else None
        salary_min, salary_max = ResumeExtractor._parse_salary(salary_text)

        english = str(result.get("english_level", "unknown")).strip()
        if english not in ALLOWED_ENGLISH:
            english = "unknown"

        return {
            "role": role,
            "city": city,
            "work_format": wf,
            "experience_years": years,
            "salary_expectation": salary_text,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "ready_to_relocate": bool(result.get("ready_to_relocate", False)),
            "stack": ResumeExtractor._to_list(result.get("stack"), LIMITS["stack"]),
            "tasks": ResumeExtractor._to_list(result.get("tasks"), LIMITS["tasks"]),
            "certifications": ResumeExtractor._to_list(
                result.get("certifications"), LIMITS["certifications"]
            ),
            "domains": ResumeExtractor._to_list(
                result.get("domains"), LIMITS["domains"]
            ),
            "programming_languages": ResumeExtractor._to_list(
                result.get("programming_languages"), LIMITS["programming_languages"]
            ),
            "english_level": english,
        }
