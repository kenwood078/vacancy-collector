import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from src.collectors.serper import SerperClient

q = "site:hh.ru/vacancy Network Engineer"

c1 = SerperClient()
print("=== with cache ===")
r1 = c1.search(q, page=1)
print(f"got {len(r1)}")

print("=== again with cache (should hit) ===")
r2 = c1.search(q, page=1)
print(f"got {len(r2)}")

print("=== no cache ===")
c2 = SerperClient(use_cache=False)
r3 = c2.search(q, page=1)
print(f"got {len(r3)}")
