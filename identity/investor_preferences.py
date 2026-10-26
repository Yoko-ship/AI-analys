"""Bounded, typed investor preferences shared by HTTP and account storage."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Interest = Literal['dividends', 'telecom', 'fundamentals', 'banks', 'insurance',
                   'energy', 'industry', 'bonds', 'low_volatility', 'growth', 'corporate']


class SortKey(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    dir: Literal['asc', 'desc']


class ScreenerFilters(BaseModel):
    sector: str = Field(default='', max_length=100)
    query: str = Field(default='', max_length=100)
    direction: Literal['all', 'gain', 'loss'] = 'all'
    period: Literal['1d', '1w', '1m', '3m', '6m', '1y', 'ytd', '3y', '5y'] = '1d'
    type: Literal['stock', 'ordinary', 'preferred', 'bond'] = 'stock'
    favoriteOnly: bool = False
    sortKeys: list[SortKey] = Field(default_factory=list, max_length=8)


class SavedScreener(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=70)
    filters: ScreenerFilters


class InvestorPreferences(BaseModel):
    investment_interests: list[Interest] | None = Field(default=None, max_length=11)
    saved_screeners: list[SavedScreener] | None = Field(default=None, max_length=30)

    @field_validator('saved_screeners')
    @classmethod
    def unique_ids(cls, values):
        if values and len({v.id for v in values}) != len(values):
            raise ValueError('Duplicate screener ids')
        return values
