from src.storage import VacancyStorage
from src.analytics.llm_extractor import VacancyExtractor
from crewai import LLM
import json

llm = LLM(
    model="openai/gpt-oss-20b",
    base_url="http://localhost:1234/v1",
    api_key="not-needed",
    temperature=0.3,
)

extractor = VacancyExtractor(llm)

with VacancyStorage() as s:
    vacancies = s.get_all(limit=3)

for v in vacancies:
    print(f"\n--- {v['name']} ---")
    result = extractor.extract(v)
    print(json.dumps(result, ensure_ascii=False, indent=2))
