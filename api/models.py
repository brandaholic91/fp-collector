from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel


class EventRequest(BaseModel):
    event_id: UUID
    event_name: Literal["page_view", "cta_click", "form_submit"]
    occurred_at: datetime
    session_id: str
    anonymous_id: str
    page_url: str
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None
    fbclid: Optional[str] = None
    consent_analytics: bool
    payload: dict = {}


class EventResponse(BaseModel):
    status: Literal["ok", "duplicate"]


class HealthResponse(BaseModel):
    ingested: int
    duplicates: int
    duplicate_rate: float
    processed: int
    failed: int


class FunnelStep(BaseModel):
    event_name: str
    count: int
    conversion_from_top: Optional[float]


class FunnelResponse(BaseModel):
    steps: list[FunnelStep]


class EventSeriesRow(BaseModel):
    date: str
    event_name: str
    count: int


class EventsResponse(BaseModel):
    series: list[EventSeriesRow]


class UtmRow(BaseModel):
    utm_source: Optional[str]
    utm_medium: Optional[str]
    events: int
    leads: int


class UtmResponse(BaseModel):
    rows: list[UtmRow]
