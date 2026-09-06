"""Explainability response contracts."""

from typing import Any

from pydantic import BaseModel, Field


class BaseScoreBreakdown(BaseModel):
    sar_raw: float
    sar_weight: float
    sar_contribution: float
    turnover_z_raw: float | None
    turnover_z_clamped: float
    turnover_z_weight: float
    turnover_z_contribution: float
    delivery_z_raw: float | None
    delivery_z_clamped: float
    delivery_z_weight: float
    delivery_z_contribution: float
    material_filing_active: bool
    material_filing_weight: float
    material_filing_contribution: float
    base_score_sum: float


class DecayAudit(BaseModel):
    event_date: str
    evaluation_date: str
    sessions_elapsed: int
    decay_rate: float
    decay_multiplier: float


class PersonalAudit(BaseModel):
    is_held: bool
    boost_held: float
    is_pinned: bool
    boost_pinned: float
    is_recently_added: bool
    boost_recently_added: float
    is_level_crossed: bool
    boost_level_crossed: float
    raw_boost_sum: float
    personal_cap: float
    effective_multiplier: float


class DecisionStep(BaseModel):
    step: int
    rule: str
    test: str
    evaluated: str
    taken: bool


class RankContext(BaseModel):
    rank: int
    total_brief_items: int
    delta_to_rank_above: float | None
    symbol_above: str | None
    delta_to_rank_below: float | None
    symbol_below: str | None
    why_ranked_here: str


class ExplainBriefItemResponse(BaseModel):
    signal_event_id: str | None = None
    session_date: str | None = None
    family: str | None = None
    classification: str | None = None
    rank: int | None = None
    item_id: str
    brief_id: str
    symbol: str
    inputs_hash: str
    data_status: str
    completeness_set: list[str]
    decision_path: list[DecisionStep]
    base_score: BaseScoreBreakdown
    decay: DecayAudit
    personal: PersonalAudit
    final_score: float
    rank_context: RankContext
    sections: list[dict[str, Any]] = Field(default_factory=list)
    completeness: list[str] = Field(default_factory=list)
