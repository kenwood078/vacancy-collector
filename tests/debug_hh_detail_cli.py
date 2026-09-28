from src.collectors.hh_client import HHClient

c = HHClient()
results = c.search('"Сетевой инженер"', area=[1], search_field="name", search_period=7)

print(f"\nВсего вакансий: {len(results)}\n")

for i, v in enumerate(results[:10], 1):
    vid = v["vacancyId"]
    detail = c._get_detail(vid)

    if not detail:
        print(f"{i}. {vid} — SKIP (None)")
        continue

    print(f"{i}. {vid} — desc={detail['description']}, skills={detail['key_skills']}, req={detail['requirements_text']}")
    print(f"   {v['name'][:70]}")