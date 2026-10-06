from src.collectors.hh_client import HHClient

c = HHClient()
results = c.search('"Сетевой инженер"', area=[1], search_field="name", search_period=7)

for v in results[:5]:
    detail = c.get_detail(v["vacancyId"])
    data = HHClient._vacancy_to_dict(v, detail)
    print("---")
    for k, val in data.items():
        preview = (str(val)[:100] + "...") if val and len(str(val)) > 100 else val
        print(f"  {k}: {preview}")
