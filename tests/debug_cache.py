from src.storage.cache import SearchCache

c = SearchCache()
k = c.make_key("test")
c.set(k, {"foo": "bar"})
print(c.get(k))  # {'foo': 'bar'}

# Меняем mtime файла на 25 часов назад
import os
import time

p = c._path(k)
old = time.time() - 25 * 3600
os.utime(p, (old, old))
print(c.get(k))  # None — истёк
