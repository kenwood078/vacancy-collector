import argparse
import json

from src.analytics.stats import compute_statistics
from src.specializations import (
    SpecializationConfigError,
    load_report_profile,
    load_specialization,
)
from src.storage import VacancyStorage

parser = argparse.ArgumentParser(description="Ручная проверка профильной статистики")
parser.add_argument("--spec", required=True, help="Ключ специализации")
args = parser.parse_args()
try:
    specialization = load_specialization(args.spec)
    profile = load_report_profile(args.spec)
except SpecializationConfigError as exc:
    parser.error(str(exc))

with VacancyStorage() as s:
    vacancies = s.get_by_professional_role(specialization["professional_role"])

print(f"Всего: {len(vacancies)}")
stats = compute_statistics(vacancies, profile["skills_keywords"])
print(json.dumps(stats, ensure_ascii=False, indent=2))
