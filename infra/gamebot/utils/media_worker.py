import httpx
from PIL import Image
from io import BytesIO
from loguru import logger
import os

class MediaWorker:
    def __init__(self, cache_dir="media_cache"):
        self.cache_dir = cache_dir
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    async def optimize_image(self, url: str, game_id: str) -> str:
        """
        Downloads, resizes, and compresses an image for Telegram previews.
        Returns the local path or a cached URL (simulation).
        """
        if not url: return None
        
        target_path = os.path.join(self.cache_dir, f"{game_id}_thumb.jpg")
        
        # Check cache
        if os.path.exists(target_path):
            return target_path

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()
                
                img = Image.open(BytesIO(response.content))
                # Convert to RGB (in case of PNG/RGBA)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                # Resize for thumbnail (e.g., 320x180)
                img.thumbnail((320, 320))
                
                # Save with compression
                img.save(target_path, "JPEG", quality=85, optimize=True)
                logger.info(f"[Media] Optimized thumbnail for {game_id}")
                return target_path
            except Exception as e:
                logger.error(f"[Media] Failed to optimize {url}: {e}")
                return url # Fallback to original URL

media_worker = MediaWorker()
