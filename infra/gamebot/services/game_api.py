import os
import httpx
import json
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from database.db import get_session
from database.models import APICache
from utils.resiliency import rawg_breaker

load_dotenv()
RAWG_API_KEY = os.getenv("RAWG_API_KEY")

async def get_cached_response(endpoint, params):
    session = get_session()
    params_str = json.dumps(params, sort_keys=True)
    expiry = int(datetime.utcnow().timestamp()) - 86400
    
    cache = session.query(APICache).filter(
        APICache.endpoint == endpoint,
        APICache.query_params == params_str,
        APICache.timestamp > expiry
    ).first()
    
    session.close()
    return json.loads(cache.response_data) if cache else None

async def set_cached_response(endpoint, params, data):
    session = get_session()
    params_str = json.dumps(params, sort_keys=True)
    
    session.query(APICache).filter(
        APICache.endpoint == endpoint,
        APICache.query_params == params_str
    ).delete()
    
    new_cache = APICache(
        endpoint=endpoint,
        query_params=params_str,
        response_data=json.dumps(data),
        timestamp=int(datetime.utcnow().timestamp())
    )
    session.add(new_cache)
    session.commit()
    session.close()

@rawg_breaker
async def get_upcoming_releases(days_ahead=7):
    if not RAWG_API_KEY: return []
    
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    endpoint = "games_upcoming"
    params = {"dates": f"{start_date},{end_date}", "ordering": "released"}
    
    cached = await get_cached_response(endpoint, params)
    if cached is not None: return cached

    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates={start_date},{end_date}&ordering=released"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json().get('results', [])
            await set_cached_response(endpoint, params, data)
            return data
        except Exception as e:
            logging.error(f"Error fetching upcoming releases: {e.__class__.__name__}")
            raise # Let circuit breaker catch it

@rawg_breaker
async def search_game(query):
    if not RAWG_API_KEY: return None
    
    endpoint = "games_search"
    params = {"search": query}
    
    cached = await get_cached_response(endpoint, params)
    if cached is not None: return cached

    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&search={query}&page_size=1"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            results = response.json().get('results', [])
            game = results[0] if results else None
            if game:
                await set_cached_response(endpoint, params, game)
            return game
        except Exception as e:
            logging.error(f"Error searching game: {e.__class__.__name__}")
            raise

from utils.localization import get_string

def format_release_message(game, lang='en'):
    release_date_str = get_string(lang, 'release_date')
    platforms_str = get_string(lang, 'platforms')
    coming_in_str = get_string(lang, 'coming_in')
    days_unit = get_string(lang, 'days')
    hours_unit = get_string(lang, 'hours')

    release_date_val = game.get('released')
    timer_text = ""
    
    if release_date_val:
        try:
            target_date = datetime.strptime(release_date_val, '%Y-%m-%d')
            now = datetime.now()
            diff = target_date - now
            
            if diff.total_seconds() > 0:
                days = diff.days
                hours = diff.seconds // 3600
                timer_text = f"\n{coming_in_str}: <b>{days} {days_unit}, {hours} {hours_unit}</b>"
            else:
                timer_text = f"\n✅ <b>{get_string(lang, 'free')}</b>" # Or something like "Released"
        except Exception:
            pass

    platforms = ", ".join([p['platform']['name'] for p in game.get('platforms', [])])
    
    # Platform Icon
    platform_icon = "📱" if game.get('platform_type') == "Mobile" else "🚀"
    
    score_text = ""
    if game.get('critic_score') is not None and game.get('critic_score') != -1:
        score_text = f"\n🏆 <b>OpenCritic: {game['critic_score']} ({game.get('critic_tier', 'N/A')})</b>"
    elif 'critic_score' in game:
        score_text = f"\n🏆 <b>Score: N/A</b>"

    text = (
        f"{platform_icon} <b>{game.get('name')}</b>\n"
        f"📅 {release_date_str}: {release_date_val}{timer_text}\n"
        f"🕹️ {platforms_str}: {platforms}{score_text}"
    )
    image = game.get('background_image')
    return text, image

def format_search_message(game, lang='en'):
    rating_str = get_string(lang, 'rating')
    released_str = get_string(lang, 'release_date')
    platforms_str = get_string(lang, 'platforms')
    
    platforms = ", ".join([p['platform']['name'] for p in game.get('platforms', [])])
    text = (
        f"🔍 <b>{game.get('name')}</b>\n"
        f"⭐ {rating_str}: {game.get('rating')}/5\n"
        f"📅 {released_str}: {game.get('released')}\n"
        f"🕹️ {platforms_str}: {platforms}"
    )
    image = game.get('background_image')
    return text, image
