"""Wire format shared by the subscription-backed news worker and the editorial desk."""
from pydantic import BaseModel, ConfigDict, Field


MAX_PITCHES = 5


class PostCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    headline: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2400)
    reason: str = Field(min_length=1, max_length=400)


class Pitch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: int
    excerpt: str = Field(min_length=1, max_length=600)
    ru: PostCopy
    uz: PostCopy


class Pitches(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Pitch] = Field(max_length=MAX_PITCHES)
