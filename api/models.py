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
