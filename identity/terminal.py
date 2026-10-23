"""Bounded panel preferences, validated at both HTTP and persistence boundaries."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TerminalPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(pattern=r"^[A-Z0-9]{2,16}$")
    func: Literal["SUM", "PL", "BS", "RAT", "FV", "RV", "DVD", "CF", "CN", "DQ", "REC"] = "SUM"
    form: Literal["NSBU", "MSFO"] = "NSBU"
    scope: Literal["separate", "consolidated"] = "separate"

    @model_validator(mode="after")
    def check_scope(self):
        if self.form == "NSBU" and self.scope != "separate":
            raise ValueError("NSBU requires separate scope")
        return self


def validate_layout(value):
    if not isinstance(value, list) or len(value) > 4:
        raise ValueError("Choose at most four panels")
    return [TerminalPanel.model_validate(p).model_dump() for p in value]
