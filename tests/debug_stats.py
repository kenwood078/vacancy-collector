import json

from src.analytics.stats import compute_statistics
from src.storage import VacancyStorage

with VacancyStorage() as s:
    vacancies = s.get_all()

print(f"Всего: {len(vacancies)}")
stats = compute_statistics(vacancies)
print(json.dumps(stats, ensure_ascii=False, indent=2))
