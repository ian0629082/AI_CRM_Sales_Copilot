from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InteractionType


class InteractionCreate(BaseModel):
    type: InteractionType
    content: str = Field(min_length=1)


class InteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    type: InteractionType
    content: str
    created_at: datetime
