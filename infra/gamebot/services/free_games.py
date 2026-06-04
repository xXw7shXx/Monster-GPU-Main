import requests

GAMERPOWER_API = "https://www.gamerpower.com/api/giveaways"

def get_free_games(platform=None):
    """
    Fetches currently available free games.
    Platform can be: 'pc', 'ps4', 'ps5', 'xbox-one', 'xbox-series-x-s', 'switch', etc.
    """
    params = {}
    if platform:
        params['platform'] = platform
    else:
        params['type'] = 'game' # Only full games, not DLCs
        
    try:
        response = requests.get(GAMERPOWER_API, params=params)
        response.raise_for_status()
        data = response.json()
        # API returns a dict with status if error, otherwise a list
        if isinstance(data, dict) and data.get("status") == 0:
            return []
        return data
    except Exception as e:
        print(f"Error fetching free games: {e}")
        return []

from utils.localization import get_string

def format_free_game_message(game, lang='en'):
    platform_str = get_string(lang, 'platform')
    value_str = get_string(lang, 'value')
    free_str = get_string(lang, 'free')
    end_date_str = get_string(lang, 'end_date')
    claim_str = get_string(lang, 'claim_here')

    text = (
        f"🎁 <b>{game.get('title')}</b>\n"
        f"{platform_str}: {game.get('platforms')}\n"
        f"{value_str}: <s>{game.get('worth')}</s> -> {free_str}\n"
        f"{end_date_str}: {game.get('end_date') or 'Unknown'}\n"
        f"<a href='{game.get('open_giveaway_url')}'>{claim_str}</a>"
    )
    image = game.get('image') or game.get('thumbnail')
    return text, image
