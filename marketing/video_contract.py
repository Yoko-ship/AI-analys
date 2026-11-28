"""Bounded creative instructions for the standalone UZStock video agent."""
from typing import Literal

from pydantic import Field, model_validator

from .models import Input

PAGES = {"home": {"path": "/", "description": "Знакомство с UZStock"},
         "news": {"path": "/news", "description": "Новости на сайте UZStock"},
         "market": {"path": "/market", "description": "Таблица ценных бумаг и данные рынка"},
         "catalog": {"path": "/catalog", "description": "Каталог компаний"}}


class VideoBrief(Input):
    brief: str = Field(min_length=10, max_length=2000)


class Scene(Input):
    headline: str = Field(min_length=3, max_length=65)
    narration: str = Field(min_length=20, max_length=350)
    page: Literal["home", "news", "market", "catalog"]


class Storyboard(Input):
    title: str = Field(min_length=3, max_length=120)
    scenes: list[Scene] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def bounded_speech(self):
        words = sum(len(scene.narration.split()) for scene in self.scenes)
        if not 30 <= words <= 155:
            raise ValueError("Use 30–155 spoken words across the complete video.")
        return self


DIRECTOR = """You are UZStock's video director. Create a standalone Russian PR or
website demonstration video from the owner's brief. This is not a Telegram post.
The output is a vertical narrated film that can be exported to any social platform.
Use a specific opening question, a useful demonstration, and a calm UZStock website
call to action. 3–6 distinct scenes, 30–155 spoken words total. Natural speech;
short readable headlines (no lists of disconnected facts). Each scene names an
available website page which the PC worker will actually record. Keep narration
about the supplied product features, not changing quotes or unverified financial
claims. Do not invent a company result, customer count, pricing, guarantee, market
news, award or investment return. The brief is creative direction, not evidence.
Do not promise functions beyond the supplied page descriptions. Never instruct
the worker to run code, use a URL, open an admin page or publish. No external source
credits; use UZStock branding and uzstock.uz. Spell UZStock normally in the script;
the voice adapter handles pronunciation. Return only the structured storyboard.
"""
