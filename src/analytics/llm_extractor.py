import json
import logging
import re

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

ALLOWED_ENGLISH = {"A1", "A2", "B1", "B2", "C1", "C2", "native", "unknown"}

LIMITS = {
    "stack": 35,
    "tasks": 15,
    "certifications": 10,
    "domains": 5,
    "programming_languages": 10,
}

PROMPT_TEMPLATE = """Ты — парсер вакансий. Извлекаешь данные из текста вакансии в JSON.

ФОРМАТ ОТВЕТА — строго эта схема, все 6 ключей обязательны:
{{
  "stack": ["string"],
  "tasks": ["string"],
  "certifications": ["string"],
  "domains": ["string"],
  "programming_languages": ["string"],
  "english_level": "A1|A2|B1|B2|C1|C2|native|unknown"
}}

ЖЁСТКИЕ ПРАВИЛА ВЫВОДА:
1. Только JSON. Без markdown, без текста до и после.
2. Каждый список — массив строк. Даже один элемент: ["Python"], не "Python".
3. Пустой список — [], а не null, "", "нет" или "отсутствует".
4. Значения бери ТОЛЬКО из текста вакансии. Не выдумывай.
5. Если для поля данных нет — возвращай [].

ПОЛЕ stack — технологии, протоколы, вендоры, ОС, инструменты.
- Канонично и коротко: "Cisco", а не "Cisco Catalyst 9300"; "Juniper", а не "Juniper MX960".
- Один вендор = одна запись. Модели, серии, версии не перечисляй.
- Аббревиатуры процессов и артефактов (HLD, LLD, ТЗ, ПМИ, L1-L3) включай в stack, если они указаны в навыках.
- Приоритет: сначала технологии из «Требования», потом из «Будет плюсом».
- Максимум 35 пунктов.

ПОЛЕ tasks — задачи из текста.
- Источник: секции «Обязанности», «Чем предстоит заниматься», «Задачи», «Что нужно делать».
- НЕ бери пункты из «Требования», «Навыки», «Будет плюсом», «Условия».
  Это навыки и требования — они идут в stack.
- Один пункт = одно действие, до 12 слов.
- Начинай с глагола в форме, подходящей по смыслу.
- Не объединяй РАЗНЫЕ действия через "и":
    «настройка VPN и мониторинг сети» → это ДВА пункта: ["настройка VPN", "мониторинг сети"].
- НО парные действия, описывающие один процесс, НЕ разбивай:
    «диагностика и устранение», «планирование и проведение», «разработка и внедрение» — это ОДИН пункт.
- Не пропускай задачи. Если их 20 — верни 20.
- Дубликаты объединяй: "мониторинг сети" == "сетевой мониторинг".

ПОЛЕ certifications — только сертификаты.
- Примеры: CCNA, CCNP, HCIA, JNCIA, IELTS, CKA.
- Технологии (Python, Linux, Cisco) сюда НЕ попадают.

ПОЛЕ domains — отрасль или сфера деятельности компании.
Хорошо: ЦОД, телеком, банк, финтех, DPI, NGFW, операторы связи, госсектор, ритейл, промышленность.
Плохо (запрещено): "IT", "сети", "сетевая инфраструктура", "корпоративная сеть",
"транспортная сеть", "Сетевая инженерия", названия технологий (Cisco, SDN, Cloud).
Не дублируй близкие понятия: есть "ЦОД" — не добавляй "транспортная сеть ЦОД".
1–5 штук. Если в тексте нет явной отрасли — верни [].

ПОЛЕ programming_languages — только языки программирования.
- Примеры: Python, Go, Java, C++, SQL, Bash.
- OSPF, BGP, VXLAN — это протоколы, НЕ языки программирования. Они идут в stack.
- Фреймворки (Django, FastAPI) сюда НЕ попадают — они в stack.

ПОЛЕ english_level — ровно одно значение из списка:
A1, A2, B1, B2, C1, C2, native, unknown.
- Если уровень не указан явно — "unknown". Не угадывай.

ПРИМЕР (копируй ТОЛЬКО формат, значения НЕ переноси в свой ответ):
Вход: "Ищем бариста. Приготовление и подача кофе, работа с кофемашиной.
Контроль качества напитков. Кассовое обслуживание клиентов. Знание английского не требуется."
Выход:
{{
  "stack": ["кофемашина", "касса"],
  "tasks": [
    "приготовление и подача кофе",
    "контроль качества напитков",
    "кассовое обслуживание клиентов"
  ],
  "certifications": [],
  "domains": ["общепит", "кофейня"],
  "programming_languages": [],
  "english_level": "unknown"
}}

Текст вакансии:
<<<
{requirements}
>>>

Верни только JSON.
"""


class VacancyExtractor:
    """Извлекает структурированные данные из вакансии через LLM."""

    def __init__(self, llm) -> None:
        """
        Args:
            llm: экземпляр CrewAI LLM с методом .call(prompt).
        """
        self.llm = llm
        self.llm_model = getattr(llm, "model", "unknown")

    def extract(self, vacancy: dict) -> dict | None:
        """
        Принимает vacancy из БД, возвращает структурированный dict или None.

        Args:
            vacancy: словарь из таблицы vacancies.

        Returns:
            Словарь с полями vacancy_id, stack, tasks, certifications,
            domains, programming_languages, english_level, llm_model,
            prompt_version — или None, если текст слишком короткий либо LLM
            вернула невалидный ответ.
        """
        text = vacancy.get("requirements") or ""
        if len(text) < 100:
            logger.info("Skip (too short): %s", vacancy.get("id"))
            return None

        prompt = PROMPT_TEMPLATE.format(requirements=text[:10000])

        try:
            raw = self.llm.call(prompt)
            cleaned = re.sub(
                r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE
            ).strip()
            result = json.loads(cleaned)
        except Exception as e:
            logger.warning("Extract failed for %s: %s", vacancy.get("id"), e)
            return None

        validated = self._validate(result)
        if validated is None:
            return None

        validated["vacancy_id"] = vacancy["id"]
        validated["llm_model"] = self.llm_model
        validated["prompt_version"] = PROMPT_VERSION
        return validated

    @staticmethod
    def _clean(item: str) -> str:
        """
        Убирает скобки, кавычки, ведущие дефисы; схлопывает пробелы.

        Example:
            'Cisco (Catalyst, Nexus)' → 'Cisco'
            '- "Python"' → 'Python'
        """
        item = re.sub(r"\s*\(.*?\)", "", item)
        item = item.strip().strip("-—•*").strip()
        item = item.strip("\"'«»").strip()
        item = re.sub(r"\s+", " ", item)
        return item.strip()

    @staticmethod
    def _to_list(value, max_n: int) -> list[str]:
        """Приводит значение к списку очищенных строк с ограничением длины."""
        if not isinstance(value, list):
            return []
        cleaned = [VacancyExtractor._clean(str(s)) for s in value if str(s).strip()]
        return [s for s in cleaned if s][:max_n]

    @staticmethod
    def _validate(result: dict) -> dict | None:
        """Проверяет структуру ответа LLM и приводит к стандарту."""
        if not isinstance(result, dict):
            logger.warning("LLM returned non-dict: %r", type(result))
            return None

        english = str(result.get("english_level", "unknown")).strip()
        if english not in ALLOWED_ENGLISH:
            english = "unknown"

        return {
            "stack": VacancyExtractor._to_list(result.get("stack"), LIMITS["stack"]),
            "tasks": VacancyExtractor._to_list(result.get("tasks"), LIMITS["tasks"]),
            "certifications": VacancyExtractor._to_list(
                result.get("certifications"), LIMITS["certifications"]
            ),
            "domains": VacancyExtractor._to_list(
                result.get("domains"), LIMITS["domains"]
            ),
            "programming_languages": VacancyExtractor._to_list(
                result.get("programming_languages"), LIMITS["programming_languages"]
            ),
            "english_level": english,
        }
