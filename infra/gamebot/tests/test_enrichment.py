import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime
from engine.enrichment_pipeline import EnrichmentPipeline
from database.schema import GameCache


@pytest.mark.asyncio
async def test_enrich_game_skips_recent():
    session = MagicMock()
    pipeline = EnrichmentPipeline(session)
    game = GameCache(title="Test Game")
    game.enriched_at = datetime.utcnow()
    result = await pipeline.enrich_game(game)
    assert result is True


@pytest.mark.asyncio
async def test_enrich_game_calls_igdb_then_steam():
    session = MagicMock()
    pipeline = EnrichmentPipeline(session)
    pipeline.igdb.enrich = AsyncMock(return_value=None)
    pipeline.steam.enrich = AsyncMock(return_value={
        "description": "A test game",
        "genres": "RPG",
        "tags": "",
        "developers": "DevCorp",
        "screenshots": [],
        "source": "steam",
    })

    game = GameCache(title="Test Game")
    result = await pipeline.enrich_game(game)

    assert result is True
    assert game.description == "A test game"
    assert game.enriched_source == "steam"
    pipeline.igdb.enrich.assert_awaited_once()
    pipeline.steam.enrich.assert_awaited_once()
