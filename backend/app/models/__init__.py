"""集中匯入所有 model。

SQLAlchemy 要能建表、要能解析 relationship 字串（例如 "Lead"），
前提是所有 model class 都已經被載入過一次。這個檔案就是負責這件事。
"""

from app.models.ai_analysis import AIAnalysis
from app.models.enums import (
    InteractionType,
    LeadLevel,
    LeadSource,
    LeadStatus,
    PropertyType,
    Purpose,
    Urgency,
)
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.models.user import User

__all__ = [
    "AIAnalysis",
    "Interaction",
    "InteractionType",
    "Lead",
    "LeadLevel",
    "LeadSource",
    "LeadStatus",
    "PropertyType",
    "Purpose",
    "Urgency",
    "User",
]
