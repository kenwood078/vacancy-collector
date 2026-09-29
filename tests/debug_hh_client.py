"""Проверка, что fetch_full извлекает все новые поля."""

from src.collectors.hh_client import HHClient

c = HHClient()

# Берём 3 вакансии
results = c.search('NAME:("Сетевой инженер")', area=[1, 2], page=0, search_period=7)
if not results:
    print("Ничего не найдено")
    raise SystemExit

print(f"Всего в выдаче: {len(results)}\n")

for v in results[:3]:
    data = c.fetch_full(v)
    if not data:
        print(f"--- SKIP {v['vacancyId']} (no detail) ---")
        continue

    print(f"--- {data['name']} ---")
    print(f"  url:                     {data['url']}")
    print(f"  city:                    {data['city']}")
    print(f"  employer:                {data['employer']}")
    print(f"  employer_id:             {data['employer_id']}")
    print(f"  employer_rating:         {data['employer_rating']}")
    print(f"  employer_reviews_count:  {data['employer_reviews_count']}")
    print(f"  salary:                  {data['salary']}")
    print(f"  salary_from:             {data['salary_from']}")
    print(f"  salary_to:               {data['salary_to']}")
    print(f"  salary_currency:         {data['salary_currency']}")
    print(f"  salary_gross:            {data['salary_gross']}")
    print(f"  experience:              {data['experience']}")
    print(f"  work_format:             {data['work_format']}")
    print(f"  employment_form:         {data['employment_form']}")
    print(f"  schedule:                {data['schedule']}")
    print(f"  professional_role:       {data['professional_role']}")
    print(f"  published_at:            {data['published_at']}")
    print(f"  responses_count:         {data['responses_count']}")
    print(f"  key_skills:              {str(data['key_skills'])[:80]}")
    print(f"  requirements:            {str(data['requirements'])[:80]}")
    print()
