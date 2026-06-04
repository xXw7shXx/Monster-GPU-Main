# 🏗️ Gamer Alert Enterprise Architecture
**Version:** 2.0 (High-Performance Async Revision)
**Date:** May 2, 2026

## 1. Executive Summary
The Gamer Alert bot has been refactored into a **Database-First, Asynchronous, Multi-Source Engine**. The core philosophy is strict decoupling: the user-facing bot (Telegram/TikTok) **never** communicates with external APIs. It only reads from a highly indexed, unified local database. A background `GlobalSyncManager` handles all external data ingestion using concurrent asynchronous requests, priority queues, and circuit breakers.

## 2. Core Architectural Principles
*   **Unified Data Modeling:** All incoming data from 5 disparate sources (RAWG, ITAD, IGDB, Steam, OpenCritic) is normalized into a strict Pydantic `GameObject` schema before touching the database.
*   **Priority-Driven Sync Engine:** 
    *   **Priority 1 (Critical):** "Free-to-Keep" deals (Epic, ITAD, GamerPower). Synced every 10 minutes.
    *   **Priority 2 (High):** "Upcoming Releases" & "Specials" (IGDB, RAWG, Steam). Synced concurrently.
    *   **Priority 3 (Background):** "Review Scores" (OpenCritic). Lazy-loaded via a Budget Manager to protect API quotas.
*   **Asynchronous Concurrency:** The sync engine uses `asyncio` and `httpx` to fetch from multiple APIs simultaneously, reducing a 15-second sync cycle to under 2 seconds.
*   **Resilience (Circuit Breakers):** If an external API (e.g., Steam) goes down or rate-limits the server, the circuit breaker trips. The sync continues for other sources without crashing the application.
*   **Zero-Latency Messaging:** User commands (`/free`, `/upcoming`) query indexed database columns (`game_type`, `release_date`), returning results instantly.

## 3. Directory Structure
```text
/
├── core/
│   ├── config.py           # Centralized Pydantic BaseSettings (loads .env)
│   ├── database.py         # SQLAlchemy async engine & session management
│   ├── models.py           # SQLAlchemy ORM models (indexed)
│   └── schemas.py          # Pydantic models for data validation (GameObject)
├── engine/
│   ├── sync_manager.py     # GlobalSyncManager (Priority Queue & Orchestration)
│   ├── circuit_breaker.py  # Fault tolerance logic
│   └── budget_manager.py   # Quota protection for RapidAPI
├── adapters/               # Asynchronous API Clients
│   ├── epic_adapter.py
│   ├── igdb_adapter.py
│   ├── itad_adapter.py
│   ├── opencritic_adapter.py
│   ├── rawg_adapter.py
│   └── steam_adapter.py
├── bot/
│   ├── handlers.py         # Telegram/TikTok command logic (DB-only reads)
│   └── notifier.py         # Outbound broadcast engine
├── main.py                 # Entry point (Initializes DB, Scheduler, and Bot)
└── requirements.txt        # Optimized dependencies
```

## 4. Data Flow Lifecycle
1.  **Ingestion:** The `GlobalSyncManager` (triggered by APScheduler every 10 mins) launches concurrent `asyncio.gather` tasks to the `adapters`.
2.  **Validation:** Adapters return raw JSON, which is immediately parsed through the `GameObject` Pydantic schema. Invalid data is dropped and logged.
3.  **Upsertion:** Validated `GameObjects` are passed to the Database layer. The system checks `last_updated` timestamps and performs an efficient bulk upsert into the `game_cache` table.
4.  **Lazy Loading:** The Budget Manager checks the OpenCritic quota. If sufficient, it selects top-tier upcoming games missing scores and fetches them sequentially.
5.  **Delivery:** A user sends `/free`. The bot queries the indexed `game_cache` table and returns the formatted response in milliseconds.
