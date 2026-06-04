import os
import httpx
import logging

class TikTokService:
    def __init__(self):
        self.client_key = os.getenv("TIKTOK_CLIENT_KEY")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
        self.access_token = os.getenv("TIKTOK_ACCESS_TOKEN")
        # Correct endpoint for TikTok Business Messaging API v2
        self.api_url = "https://open.tiktokapis.com/v2/business/message/send/"

    async def send_message(self, recipient_id: str, text: str):
        """
        Sends a message to a TikTok user via the Business Messaging API.
        """
        if not self.access_token or self.access_token == "your_access_token":
            logging.warning("TikTok access token is not valid. Please update .env")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Payload for v2 Business Messaging
        payload = {
            "recipient_id": recipient_id,
            "message": {
                "text": text
            }
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.api_url, json=payload, headers=headers)
                # Log response for debugging
                if response.status_code != 200:
                    logging.error(f"TikTok API Error: {response.status_code} - {response.text}")
                response.raise_for_status()
                return True
            except Exception as e:
                logging.error(f"Error sending TikTok message: {e}")
                return False

    async def send_photo(self, recipient_id: str, photo_url: str, caption: str = ""):
        """
        Sends a photo message to a TikTok user.
        Note: TikTok's Messaging API has specific requirements for media.
        This is a simplified implementation.
        """
        # TikTok might require uploading the image first or using a specific format.
        # For now, we'll send the text + URL as a fallback if images aren't directly supported via URL.
        message_text = f"{caption}\n\n{photo_url}" if caption else photo_url
        return await self.send_message(recipient_id, message_text)

tiktok_service = TikTokService()
