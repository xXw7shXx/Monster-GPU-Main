"""Compatibility imports for sync SQLAlchemy models."""

from database.schema import (
    APICache,
    APILimit,
    ActivityLog,
    Base,
    ContentQueue,
    GameCache,
    GameEmbedding,
    MaintenanceLog,
    NotifiedDeal,
    OAuthToken,
    Preferences,
    RecommendationHistory,
    SyncHistory,
    User,
    UserTasteProfile,
)

__all__ = [
    "APICache",
    "APILimit",
    "ActivityLog",
    "Base",
    "ContentQueue",
    "GameCache",
    "GameEmbedding",
    "MaintenanceLog",
    "NotifiedDeal",
    "OAuthToken",
    "Preferences",
    "RecommendationHistory",
    "SyncHistory",
    "User",
    "UserTasteProfile",
]
