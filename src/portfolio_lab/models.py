"""Explicit contracts. Unknowns never default to zero exposures or free trades."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(StrictModel):
    code: str = Field(pattern=r"^\d{6}$")
    name: str
    as_of: date
    venue: str
    market_value: float = Field(gt=0)
    quantity: float | None = Field(default=None, gt=0)
    cost_basis: float | None = Field(default=None, ge=0)
    restriction: str | None = None
    user_thesis: str | None = None
    notes: str | None = None


class Holding(StrictModel):
    fund: str
    security: str
    name: str
    weight: float = Field(ge=0, le=1)
    holding_date: date
    published_date: date | None = None
    source_id: str
    scope: Literal["top10", "partial", "full_equity", "full_gold", "full_assets", "pcf", "feeder"]
    kind: Literal["equity", "fund", "gold", "cash", "bond", "other"] = "equity"
    region: str | None = None
    currency: str | None = None
    sector: str | None = None
    classification_source: str | None = None


class Constraints(StrictModel):
    """Model domain is long-only, fully invested. Optional personal constraints are empty."""

    min_weights: dict[str, float] = Field(default_factory=dict)
    max_weights: dict[str, float] = Field(default_factory=dict)
    max_turnover: float | None = Field(default=None, ge=0, le=1)
    max_volatility: float | None = Field(default=None, gt=0)
    group_caps: dict[str, float] = Field(default_factory=dict)
    groups: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_bounds(self):
        for k, v in list(self.min_weights.items()) + list(self.max_weights.items()):
            if not 0 <= v <= 1:
                raise ValueError(f"Weight outside [0,1]: {k}")
        for k in self.min_weights.keys() | self.max_weights.keys():
            if self.min_weights.get(k, 0) > self.max_weights.get(k, 1):
                raise ValueError(f"Inconsistent bounds: {k}")
        if any(k not in self.groups for k in self.group_caps):
            raise ValueError("Every group cap needs a named group")
        if any(len(v) != len(set(v)) for v in self.groups.values()):
            raise ValueError("Duplicate product in group")
        if any(not 0 <= v <= 1 for v in self.group_caps.values()):
            raise ValueError("Group caps outside [0,1]")
        return self


class ResearchConfig(StrictModel):
    as_of: date
    start: date
    frequency: Literal["weekly"] = "weekly"
    base_currency: Literal["CNY"] = "CNY"
    max_nav_age_days: int = Field(default=4, ge=0, le=10)
    min_observations: int = Field(default=40, ge=20)
    disclosure_max_age_days: int = Field(default=120, ge=0)
    constraints: Constraints = Field(default_factory=Constraints)
    cost_bps_scenarios: list[float] = Field(default_factory=lambda: [0, 10, 50, 150])
    optimization_cost_bps: float = Field(default=50, ge=0)
    bootstrap_samples: int = Field(default=500, ge=100)
    seed: int = 20260929

    @model_validator(mode="after")
    def valid_window(self):
        if self.start >= self.as_of:
            raise ValueError("start must precede as_of")
        if any(x < 0 for x in self.cost_bps_scenarios):
            raise ValueError("Costs cannot be negative")
        return self
