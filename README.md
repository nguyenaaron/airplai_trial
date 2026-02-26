# AirPLAi Event Tagging API

Backend API for tagging and querying moments in youth basketball games. Coaches, camera operators, or AI systems send tagged events (shots, fouls, rebounds, etc.) and the API stores them, maintains live box scores, and serves highlight-ready clips.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

The API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Running Tests

```bash
pytest tests/ -v
```

Uses a separate `test.db` so your dev data is untouched.

## Project Structure

```
main.py              Entry point — creates the FastAPI app and registers routers
database.py          SQLite connection, session factory, Base class
enums.py             EventType, Period, ShotType enums
models.py            SQLAlchemy models (Game, Player, GameEvent, stats tables)
schemas.py           Pydantic request/response schemas with validation
stats.py             Stats engine — updates denormalized box scores on each event
routes/
  games.py           POST/GET /games
  events.py          POST/GET/PATCH/DELETE /games/{id}/events, timeline, highlights
  players.py         POST /players
  stats.py           GET player/team stats, season stats, shot charts, rebuild
tests/
  test_api.py        Test suite covering CRUD, stats, validation, shot charts
```

## API Endpoints

### Games
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/games` | Create a game |
| GET | `/games/{game_id}` | Get a game |

### Events
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/games/{game_id}/events` | Tag an event (auto-updates stats) |
| GET | `/games/{game_id}/events` | List events (filter by type, period, player) |
| PATCH | `/games/{game_id}/events/{event_id}` | Update an event |
| DELETE | `/games/{game_id}/events/{event_id}` | Delete an event |
| GET | `/games/{game_id}/timeline` | Chronological event feed |
| GET | `/games/{game_id}/highlights` | Camera-linked events above confidence threshold |
| GET | `/players/{player_id}/highlights` | All clips for a player across games |

### Players
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/players` | Create a player |

### Stats
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/games/{game_id}/stats/players` | Player box scores for a game |
| GET | `/games/{game_id}/stats/teams` | Team box scores for a game |
| GET | `/games/{game_id}/shot-chart` | Shot locations with coordinates (filter by player, team, period) |
| GET | `/players/{player_id}/stats` | Player stats across games |
| GET | `/players/{player_id}/season-stats` | Aggregated season stats with PLAi Score |
| GET | `/teams/{team_id}/season-stats` | Team season stats (W/L, ORtg, DRtg, pace) |
| POST | `/games/{game_id}/stats/rebuild` | Wipe and recalculate stats from events |

## Key Design Decisions

- **Time as integers** — `game_clock_seconds` stores seconds remaining, not strings like "Q2 4:32"
- **Denormalized stats** — box scores update incrementally on each event for instant reads
- **Confidence field** — every event has a 0.0-1.0 confidence score so AI tagging is a drop-in upgrade
- **Camera handoff** — `camera_id` + `video_timestamp_seconds` link events to raw footage for clip generation
- **Shot coordinates** — optional `court_x`/`court_y` fields (feet) for shot chart visualizations
- **Score snapshots** — `home_score_after`/`away_score_after` stored per event so dashboards don't re-aggregate

## Stack

- Python, FastAPI, SQLAlchemy, Pydantic
- SQLite for local dev (swap to Postgres for production)
