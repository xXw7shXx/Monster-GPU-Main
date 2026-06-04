# Placeholder for scraping subscription services
def get_games_leaving_soon():
    """Return real leaving-service data when a provider is configured.

    The previous implementation returned mock titles, which could mislead users.
    Until a real provider is connected, return an empty list so the command uses
    the existing no-data message.
    """
    return []

from utils.localization import get_string

def format_leaving_message(game, lang='en'):
    leaving_str = get_string(lang, 'leaving')
    date_str = get_string(lang, 'date')

    text = (
        f"⚠️ <b>{game['title']}</b>\n"
        f"{leaving_str}: {game['service']}\n"
        f"{date_str}: {game['leaving_date']}"
    )
    return text, None
