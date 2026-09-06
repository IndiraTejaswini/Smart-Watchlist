"""Brief response contract shared by the API and the frontend boundary."""

from typing import Any

from pydantic import BaseModel


class BriefCursorResponse(BaseModel):
    acknowledged_through: str
    sessions_elapsed: int = 0
    calendar_days_elapsed: int = 0


class BriefMetricsResponse(BaseModel):
    pct_move: float
    scar: float
    turnover_z: float
    delivery_z: float
    delivery_pct: float
    mpm_triggered: bool
    mpm_threshold_used: float


class BriefItemResponse(BaseModel):
    signal_event_id: str
    symbol: str
    company_name: str
    family: str
    classification: str
    rank: int
    score: float
    what: str
    how_unusual: str
    cause: str
    freshness: str
    metrics: BriefMetricsResponse
    provisional: bool
    revision: int
    was_restated: bool
    completeness: list[str]
    linked_announcement_ids: list[int]
    links: dict[str, str | None]


class BriefResponse(BaseModel):
    generated_at: str
    cursor: BriefCursorResponse
    headline: str
    market_rollup: dict[str, Any]
    items: list[BriefItemResponse]
    sector_groups: list[dict[str, Any]]
    corporate_action_notices: list[dict[str, Any]]
    quiet: dict[str, Any]
    budget: dict[str, int]
    data_quality: dict[str, Any]
