from src.collectors.hh_client import HHClient

c = HHClient()
r = c.search(query="Сетевой инженер", area= [1, 2], search_field="name")
print(len(r))
if r:
    print(r)