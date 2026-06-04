# Research: Movie Bot & Multi-Bot Admin Strategy

## TMDB API (The Movie Database)
- **Endpoint**: `https://api.themoviedb.org/3/`
- **Key Features**:
  - `search/multi`: Search for movies, TV shows, and people in one request.
  - `movie/upcoming` & `tv/on_the_air`: For upcoming/new content.
  - `language` support: Pass `ar-SA` or `en-US` to get localized content.
- **Authentication**: Bearer Token or API Key in query params.

## Multi-Bot Admin Strategy
### Current State
Admin Backend has hardcoded:
```python
BOTS = {
    "gamebot": {
        "url": os.getenv("GAMEBOT_API_URL", "http://localhost:8000"),
        "api_key": os.getenv("INTERNAL_API_KEY", "enterprise_secret")
    }
}
```

### Proposed State (Refactor)
1. **Dynamic Configuration**: Introduce a `bots.json` or a small database table in the Admin Backend to store bot metadata.
2. **Standard Bot API Contract**:
   Every bot must implement:
   - `GET /stats`: Basic health and user counts.
   - `GET /analytics`: Detailed engagement metrics.
   - `POST /announce`: Send broadcast message.
   - `GET /users`: List of registered users.
3. **Unified Frontend**:
   - The UI should loop over the `BOTS` list.
   - Add a "Global Broadcast" feature that iterates through all bots.

## Movies & TV Bot Architecture
- **Structure**: Clone `infra/gamebot` structure to `infra/moviebot`.
- **Database**: Each bot has its own SQLite database (`movie_data.db`) for user preferences and local cache (to avoid hitting TMDB rate limits too often).
- **Services**:
  - `movie_api.py`: Wrapper for TMDB.
  - `bot.py`: Telegram bot handlers.
  - `api.py`: Internal API for Admin Panel.
