import logging

from crewai import LLM

from src.collectors.pipeline import collect_serper

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

llm = LLM(
    model="openai/ornith-1.0-9b-mlx@8bit",
    base_url="http://localhost:1234/v1",
    api_key="not-needed",
)

query = 'site:hh.ru/vacancy (intitle:"Network Engineer" OR intitle:"Сетевой инженер") (Москва OR "Санкт-Петербург") -архив -стажер -junior'

added, errors, attempts = collect_serper(n_vacancies=5, query=query, llm=llm)
print(f"\nAdded: {added}, errors: {errors}, attempts: {attempts}")
