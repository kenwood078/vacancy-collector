from src.tools.check_url_tool import CheckUrlTool

tool = CheckUrlTool()
q = "hh.ru"

print(tool._run(q))   # первый раз — идёт в Serper, сохраняет в data/cache/
print(tool._run(q))   # второй раз — читает из кэша, моментально

