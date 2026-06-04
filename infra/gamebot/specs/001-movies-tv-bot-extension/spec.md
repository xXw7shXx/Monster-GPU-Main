# Feature Specification: Movies & TV Shows Bot & Multi-Bot Admin Infrastructure

**Feature Branch**: `002-movies-tv-bot-infra-upgrade`  
**Created**: 2026-05-03  
**Status**: Draft  
**Input**: Plan a new Movies & TV Shows bot extension, integrate Admin Panel with Nginx Proxy Manager (NPM) for internet access, and refactor for multi-bot scalability.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Secure Internet Access for Admin Panel (Priority: P1)
An administrator wants to access the Super Admin Panel from the internet (via a secure domain like `admin.example.com`) without exposing internal backend ports directly.

**Why this priority**: Remote management is essential for operational flexibility.

**Independent Test**: Navigate to the configured subdomain (e.g., `http://admin.local` in dev or a real domain) and log in through the NPM-proxied frontend.

**Acceptance Scenarios**:
1. **Given** NPM is running, **When** the proxy host is configured to point to `admin_frontend:80`, **Then** the dashboard is accessible via the domain.
2. **Given** an internet connection, **When** accessing the domain, **Then** all API calls are correctly routed through the frontend proxy to the backend.

---

### User Story 2 - Dynamic Multi-Bot Management (Priority: P1)
An administrator wants to add new bots (like the upcoming Movie Bot) to the dashboard by simply updating a configuration file or environment variable, without code changes.

**Why this priority**: Enables rapid scaling of the bot network.

**Independent Test**: Add a new bot entry to `bots.json`, restart the admin service, and verify the new bot appears in the dashboard UI.

**Acceptance Scenarios**:
1. **Given** a `bots.json` configuration file, **When** a new bot is added, **Then** the Admin Panel dynamically populates the bot list in the sidebar/tabs.
2. **Given** a "Global Broadcast" command, **When** executed, **Then** the system iterates through all registered bots and sends the announcement.

---

### User Story 3 - Movie/TV Show Search (Priority: P2)
A user wants to find details about a specific movie or TV show by typing its name in Arabic or English.

**Why this priority**: Core value for the new bot extension.

**Independent Test**: User sends `/search Inception` and receives a localized response.

**Acceptance Scenarios**:
1. **Given** the Movie Bot is active, **When** a user sends `/search [title]`, **Then** the bot returns TMDB data.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Admin Panel MUST be accessible via Nginx Proxy Manager (NPM) using a standard domain/subdomain.
- **FR-002**: Admin Backend MUST load bot configurations (URL, API Key, Name) from a `bots.json` file or environment variable.
- **FR-003**: Frontend MUST dynamically render bot-specific stats and controls based on the backend bot list.
- **FR-004**: Bot MUST integrate with TMDB API and support Arabic/English localization.
- **FR-005**: All bots MUST implement a standardized API contract for telemetry and broadcasting.

### Key Entities

- **BotRegistry**: Central configuration for all managed bots (id, label, api_url, api_key).
- **MediaContent**: Movie/TV Show metadata from TMDB.
- **UserSession**: Secured session for Admin access.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Admin Dashboard MUST be accessible via domain name with < 500ms initial load time.
- **SC-002**: Adding a new bot MUST require 0 code changes (only configuration update).
- **SC-003**: Movie search response time MUST be < 2 seconds.

## Assumptions

- Nginx Proxy Manager is the primary entry point for all web traffic.
- TMDB API is used as the primary data source for movies/TV.
- The infrastructure has enough resources to run multiple bot containers simultaneously.
