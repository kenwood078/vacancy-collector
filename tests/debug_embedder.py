"""Проверка Qwen3-Embedding-4B через LM Studio."""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/") + "/embeddings"
MODEL = "text-embedding-qwen3-embedding-4b"
API_KEY = os.getenv("LLM_API_KEY", "not-needed")


def embed(text: str) -> list[float]:
    r = requests.post(
        URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        json={"model": MODEL, "input": text},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def main() -> None:
    print(f"URL: {URL}")
    print(f"Model: {MODEL}\n")

    # 1. Размерность
    vec = embed("сетевой инженер")
    print(f"dimension: {len(vec)}")
    print(f"first 5 values: {[round(v, 4) for v in vec[:5]]}\n")

    # 2. Документ без префикса
    doc = (
        "Сетевой инженер. Стек: Cisco, BGP, OSPF, Linux. Задачи: настройка, мониторинг."
    )
    t0 = time.time()
    v_doc = embed(doc)
    print(f"document embed: {time.time() - t0:.2f}s")

    # 3. Запрос с инструкцией (как требует Qwen3)
    query = (
        "Instruct: Given a resume, retrieve relevant job vacancies\n"
        "Query: Ищу работу сетевого инженера, знаю Cisco, BGP, Linux."
    )
    t0 = time.time()
    v_q = embed(query)
    print(f"query embed:    {time.time() - t0:.2f}s\n")

    # 4. Косинус между документом и запросом
    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb)

    print(f"cosine (doc vs query): {cos(v_doc, v_q):.4f}")


if __name__ == "__main__":
    main()
