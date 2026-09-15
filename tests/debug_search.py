from src.collectors.scraper import scrape

text = scrape("https://hh.ru/vacancy/137067392")
print(len(text))
print(text)