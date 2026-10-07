from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

ECOMMERCE_EVENTS = ("view_item", "add_to_cart", "begin_checkout", "purchase")


class EventRequest(BaseModel):
    event_id: UUID
    event_name: Literal[
        "page_view", "cta_click", "form_submit",
        "view_item", "add_to_cart", "begin_checkout", "purchase",
    ]
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

    @model_validator(mode="after")
    def _purchase_payload(self):
        if self.event_name != "purchase":
            return self
        p = self.payload
        for key in ("order_id", "currency", "customer_key"):
            if not isinstance(p.get(key), str) or not p[key]:
                raise ValueError(f"purchase payload: '{key}' is required")
        value = p.get("value")
        # bool is a subclass of int in Python, so True would pass as 1.
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("purchase payload: 'value' must be a positive number")
        return self


class EventResponse(BaseModel):
    status: Literal["ok", "duplicate"]


class BatchRequest(BaseModel):
    events: list[EventRequest] = Field(min_length=1, max_length=1000)


class BatchResponse(BaseModel):
    accepted: int
    duplicates: int
    consent_rejected: int


class HealthResponse(BaseModel):
    ingested: int
    pending: int
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
