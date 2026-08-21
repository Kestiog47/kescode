"""OpenAI model factory."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def create_model() -> ChatOpenAI:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError(
            "API_KEY is required. Set it in .env or the environment."
        )
    return ChatOpenAI(
        model=os.getenv("MODEL", "deepseek-v4-flash"),
        base_url=os.getenv("BASE_URL", "https://api.deepseek.com"),
        api_key=api_key,
        temperature=0,
    )
