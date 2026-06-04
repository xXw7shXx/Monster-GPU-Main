import httpx
import json
import asyncio

async def test_tiktok_interaction():
    url = "http://localhost:8000/tiktok/webhook"
    
    # Simulating a user sending 'start' to the bot
    payload = {
        "event": "message",
        "data": {
            "sender_id": "test_tiktok_user_123",
            "content": "start"
        }
    }
    
    print(f"--- Simulating TikTok Message Event ---")
    print(f"Target: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            print(f"\nResponse Status: {response.status_code}")
            print(f"Response Body: {response.text}")
            
            if response.status_code == 200:
                print("\n✅ Internal processing successful!")
                print("Note: The actual reply to TikTok will fail unless a valid TIKTOK_ACCESS_TOKEN is provided in .env.")
            else:
                print("\n❌ Webhook endpoint failed.")
                
    except Exception as e:
        print(f"\n❌ Error connecting to bot API: {e}")

if __name__ == "__main__":
    asyncio.run(test_tiktok_interaction())
