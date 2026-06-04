# Implementation Plan: Infrastructure Integration & Multi-Bot Scalability

**Branch**: `002-movies-tv-bot-infra-upgrade` | **Date**: 2026-05-03

## Summary
Refactor the Admin Panel for multi-bot dynamic configuration, integrate it with Nginx Proxy Manager for secure internet access, and deploy the new Movies & TV Shows bot.

## Technical Context
- **Reverse Proxy**: Nginx Proxy Manager (NPM)
- **Domain Strategy**: `admin.yourdomain.com` (Subdomain)
- **Multi-Bot Storage**: `bots.json` configuration in `admin/backend/`
- **Bot Stack**: FastAPI + Telegram/TikTok + TMDB API

## Phase 1: Infrastructure Integration (Internet Access) [IN PROGRESS]
1.  **NPM Configuration**:
    - [ ] Add a new Proxy Host in NPM.
    - [ ] Domain: `admin.yourdomain.com` (or similar).
    - [ ] Forward Host: `super_admin_frontend`.
    - [ ] Forward Port: `80`.
2.  **Network Alignment**:
    - [x] Admin Panel moved to `/root/infra/admin`.
    - [x] Both `admin_frontend` and `admin_backend` are on the `infra-network`.
3.  **Frontend Update**:
    - [x] `nginx.conf` updated for relative proxying.
    - [x] `index.html` refactored for Multi-Bot support.

## Phase 2: Multi-Bot Refactor (Admin Panel) [COMPLETED]
1.  **Backend (FastAPI)**:
    - [x] `bots.json` created for bot registry.
    - [x] `main.py` refactored to proxy `/api/stats`, `/api/users`, and `/api/ops`.
    - [x] Standardized API contract enforced across all bot proxying.
2.  **Frontend (React)**:
    - [x] Dynamic bot list loading from `/api/config/bots`.
    - [x] UI updated with Bot Selector.

## Phase 3: Movie & TV Bot Development [PLANNED]
1.  **Scaffold**: Clone `gamebot` to `moviebot`.
2.  **Service Integration**:
    - [ ] Implement TMDB API service.
    - [ ] Register `moviebot` in the Admin Panel's `bots.json`.
3.  **Docker Update**:
    - [x] `moviebot` placeholder added to `infra/docker-compose.yml`.

## Phase 4: Validation
1.  [ ] Verify external access to Admin Panel via NPM.
2.  [ ] Verify both GameBot and MovieBot appear in the dashboard.
