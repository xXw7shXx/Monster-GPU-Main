import google.generativeai as genai
from loguru import logger
import os
import json
from core.schemas import GameObject
from core.config import settings

class ContentDrafter:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        if self.api_key and self.api_key != "your_gemini_api_key":
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(settings.GEMINI_MODEL_ID)
        else:
            self.model = None

    async def generate_drafts(self, game: GameObject) -> dict:
        """
        Generates structured viral-ready TikTok script and Telegram caption.
        Returns: {'tiktok': str, 'telegram': str}
        """
        if not self.model:
            return {
                "tiktok": f"Check out {game.title}! Score: {game.critic_score}",
                "telegram": f"🔥 {game.title} is now available! Score: {game.critic_score}"
            }

        prompt = (
            "System: You are an expert gaming trend analyst. Provide a JSON response for the game provided.\n"
            f"Game: {game.title} | Platforms: {game.platforms} | Score: {game.critic_score} | Hype: {game.hype_score}\n"
            "JSON structure:\n"
            "{\n"
            "  'vibe': 'Masterpiece'|'Hidden Gem'|'Skip'|'Trending',\n"
            "  'tiktok': 'high-energy viral script (max 200 chars)',\n"
            "  'telegram': 'catchy caption with emojis',\n"
            "  'priority': 1-10\n"
            "}"
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text)
            return {
                "vibe": data.get("vibe", "Unknown"),
                "tiktok": data.get("tiktok", ""),
                "telegram": data.get("telegram", ""),
                "priority": data.get("priority", 5)
            }
        except Exception as e:
            logger.error(f"[AI] Gemini drafting failed: {e}")
            return {
                "vibe": "Active",
                "tiktok": f"Check out {game.title}! Score: {game.critic_score}",
                "telegram": f"🔥 {game.title} is trending! Critical score: {game.critic_score}.",
                "priority": 5
            }

    def is_asset_flip(self, game: GameObject) -> bool:
        """
        Dynamic Budgeting: Checks for signs of low-quality asset-flip software.
        """
        low_quality_keywords = ["asset", "pack", "bundle", "engine", "demo", "pro", "free", "template"]
        title_lower = game.title.lower()
        
        # Heuristics for skipping
        if any(kw in title_lower for kw in low_quality_keywords) and game.critic_score is None:
            return True
        if game.critic_score and game.critic_score < 40:
            return True
        return False

content_drafter = ContentDrafter()
