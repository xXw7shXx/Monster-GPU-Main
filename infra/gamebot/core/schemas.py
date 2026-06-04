from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime

class GameObject(BaseModel):
    external_id: str = Field(..., description="Unique ID from the source (e.g., IGDB-1234)")
    title: str = Field(..., description="Game Title")
    platforms: str = Field(default="", description="Comma-separated list of platforms")
    original_price: Optional[int] = Field(default=0, description="Price in cents")
    current_price: Optional[int] = Field(default=0, description="Price in cents")
    release_date: Optional[datetime] = Field(default=None, description="Release date if known")
    expiry_date: Optional[datetime] = Field(default=None, description="When the deal expires")
    store_link: Optional[str] = Field(default=None, description="Link to the store page")
    image_url: Optional[str] = Field(default=None, description="Cover or promotional image")
    thumbnail_url: Optional[str] = Field(default=None, description="Resized thumbnail for previews")
    source_name: str = Field(..., description="Source identifier (e.g., 'igdb', 'steam')")
    game_type: str = Field(..., description="Classification ('free', 'upcoming', 'special')")
    
    # BI & Hype Metrics
    hype_score: int = Field(default=0)
    cost_per_deal: float = Field(default=0.0)
    
    # Platform & Monetization
    platform_type: str = Field(default="PC", description="'PC', 'Mobile', 'Console'")
    monetization_tags: Optional[str] = Field(default=None, description="e.g., 'Ads', 'IAP', 'Free'")
    is_limited_time: bool = Field(default=False, description="Is this a limited-time freebie?")
    
    # OpenCritic specific fields
    critic_score: Optional[int] = Field(default=None, description="OpenCritic Score (0-100)")
    critic_tier: Optional[str] = Field(default=None, description="OpenCritic Tier (e.g., 'Mighty')")

    class Config:
        from_attributes = True
