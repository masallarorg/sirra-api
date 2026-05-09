from pydantic import BaseModel


class SubscriptionStatus(BaseModel):
    user_id: str
    active: bool
    entitlement: str
    provider: str
    expires_at: str | None = None
