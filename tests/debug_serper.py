from src.collectors.serper import SerperClient

client = SerperClient()
r1 = client.search("site:hh.ru/vacancy Network Engineer", page=2)
r2 = client.search("site:hh.ru/vacancy Network Engineer")
print(r1)   # разные
print(r2[0]["link"])   # ссылки