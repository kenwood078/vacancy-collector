from crewai import LLM

from src.collectors.extractor import extract_vacancy
from src.collectors.scraper import scrape

llm = LLM(
    model="openai/ornith-1.0-9b-mlx@8bit",
    base_url="http://localhost:1234/v1",
    api_key="not-needed",
)

url = "https://hh.ru/vacancy/137067392"
text = scrape(url)
data = extract_vacancy(text, url, llm)
print(data)
