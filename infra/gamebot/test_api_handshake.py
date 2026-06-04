import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("INTERNAL_API_KEY", "enterprise_secret")
BOT_URL = "http://localhost:8000"

async def test_handshake():
    print(f"Testing API Handshake with key: {API_KEY}")
    async with httpx.AsyncClient() as client:
        try:
            # Test /stats
            resp = await client.get(f"{BOT_URL}/stats", headers={"X-API-KEY": API_KEY})
            print(f"Stats Response ({resp.status_code}): {resp.json()}")
            
            # Test /analytics
            resp = await client.get(f"{BOT_URL}/analytics", headers={"X-API-KEY": API_KEY})
            print(f"Analytics Response ({resp.status_code}): {resp.json()}")
            
            if resp.status_code == 200:
                print("✅ Handshake Successful!")
            else:
                print(f"❌ Handshake Failed: {resp.status_code}")
        except Exception as e:
            print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_handshake())
