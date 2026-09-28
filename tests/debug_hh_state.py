"""Извлекаем JSON из HH-Lux-InitialState."""
import json

from bs4 import BeautifulSoup

with open("hh_response.html", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
template = soup.find("template", id="HH-Lux-InitialState")
if not template:
    raise ValueError("HH-Lux-InitialState не найден")

raw = template.string or template.get_text()
print(f"Длина raw: {len(raw)}")
data = json.loads(raw)
print("Ключи верхнего уровня:", list(data.keys())[:30])

result = data["vacancySearchResult"]
print(f"\nВсего: {result['totalResults']}")
print(f"На странице: {len(result['vacancies'])}")
print(f"Pages: {result['paging']['pages']}")

sample = result["vacancies"][0]
print("\n=== Первая вакансия ===")
for k in sorted(sample.keys()):
    v = sample[k]
    preview = f"{type(v).__name__}[{len(v)}]" if isinstance(v, (dict, list)) else repr(v)[:80]
    print(f"  {k}: {preview}")

sample = result["vacancies"][0]
print("\n=== company ===")
print(json.dumps(sample["company"], ensure_ascii=False, indent=2))
print("\n=== area ===")
print(json.dumps(sample["area"], ensure_ascii=False, indent=2))
print("\n=== compensation ===")
print(json.dumps(sample["compensation"], ensure_ascii=False, indent=2))
print("\n=== workFormats ===")
print(json.dumps(sample["workFormats"], ensure_ascii=False, indent=2))
print("\n=== publicationTime ===")
print(json.dumps(sample["publicationTime"], ensure_ascii=False, indent=2))
# Ищем вакансию с зарплатой
print("\n=== Вакансии с зарплатой ===")
for v in result["vacancies"]:
    c = v.get("compensation", {})
    if "noCompensation" not in c:
        print(f"\n{v['name']} @ {v['company']['name']}")
        print(json.dumps(c, ensure_ascii=False, indent=2))
        break
else:
    print("Все вакансии без зарплаты")