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

## Usage Examples

Below is a full walkthrough: create a game, register players, tag events, and query stats — all via `curl`.

### 1. Create a game

**Request:**
```bash
curl -X POST http://localhost:8000/games \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Lakers vs Spurs - Week 5",
    "home_team_id": "lakers",
    "away_team_id": "spurs"
  }'
```

**Response:**
```json
{
  "id": 1,
  "name": "Lakers vs Spurs - Week 5",
  "home_team_id": "lakers",
  "away_team_id": "spurs",
  "date": "2026-02-28T00:00:00",
  "created_at": "2026-02-28T19:30:00.123456"
}
```

### 2. Register players

```bash
curl -X POST http://localhost:8000/players \
  -H "Content-Type: application/json" \
  -d '{"name": "LeBron James", "team_id": "lakers", "jersey_number": "23"}'
```
```json
{"id": 1, "name": "LeBron James", "team_id": "lakers", "jersey_number": "23"}
```

```bash
curl -X POST http://localhost:8000/players \
  -H "Content-Type: application/json" \
  -d '{"name": "Victor Wembanyama", "team_id": "spurs", "jersey_number": "1"}'
```
```json
{"id": 2, "name": "Victor Wembanyama", "team_id": "spurs", "jersey_number": "1"}
```

### 3. Tag events during a game

**LeBron drives for a 2-pointer (manual tag, full confidence):**
```bash
curl -X POST http://localhost:8000/games/1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "SHOT_MADE",
    "period": "Q1",
    "game_clock_seconds": 420,
    "player_id": 1,
    "team_id": "lakers",
    "shot_type": "TWO_POINT",
    "court_x": 12.5,
    "court_y": 8.0,
    "home_score_after": 2,
    "away_score_after": 0
  }'
```

**Response:**
```json
{
  "id": 1,
  "game_id": 1,
  "event_type": "SHOT_MADE",
  "period": "Q1",
  "game_clock_seconds": 420,
  "player_id": 1,
  "second_player_id": null,
  "team_id": "lakers",
  "camera_id": null,
  "video_timestamp_seconds": null,
  "confidence": 1.0,
  "shot_type": "TWO_POINT",
  "court_x": 12.5,
  "court_y": 8.0,
  "home_score_after": 2,
  "away_score_after": 0,
  "created_at": "2026-02-28T19:31:05.654321"
}
```

**Wemby hits a 3 — AI-detected with camera link (for clip generation):**
```bash
curl -X POST http://localhost:8000/games/1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "SHOT_MADE",
    "period": "Q2",
    "game_clock_seconds": 180,
    "player_id": 2,
    "team_id": "spurs",
    "shot_type": "THREE_POINT",
    "camera_id": "cam-court-1",
    "video_timestamp_seconds": 1423.7,
    "confidence": 0.92,
    "home_score_after": 15,
    "away_score_after": 15
  }'
```

**LeBron dishes an assist to a teammate:**
```bash
curl -X POST http://localhost:8000/games/1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "ASSIST",
    "period": "Q2",
    "game_clock_seconds": 180,
    "player_id": 1,
    "second_player_id": 3,
    "team_id": "lakers"
  }'
```

**Wemby blocks LeBron:**
```bash
curl -X POST http://localhost:8000/games/1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "BLOCK",
    "period": "Q1",
    "game_clock_seconds": 300,
    "player_id": 2,
    "team_id": "spurs"
  }'
```

### 4. Query events with filters

**All Q1 events:**
```bash
curl "http://localhost:8000/games/1/events?period=Q1"
```

**Only rebounds:**
```bash
curl "http://localhost:8000/games/1/events?event_type=REBOUND"
```

**All events involving LeBron (player 1):**
```bash
curl "http://localhost:8000/games/1/events?player_id=1"
```

### 5. View the game timeline

```bash
curl http://localhost:8000/games/1/timeline
```

Returns all events in chronological order (by period, then descending clock). Same schema as the events list.

### 6. Get highlight clips

**All camera-linked events (for clip generation service):**
```bash
curl http://localhost:8000/games/1/highlights
```

**Only high-confidence clips (AI threshold):**
```bash
curl "http://localhost:8000/games/1/highlights?min_confidence=0.9"
```

**All highlights for LeBron across games (parent-facing):**
```bash
curl "http://localhost:8000/players/1/highlights?min_confidence=0.8"
```

Returns only events that have both `camera_id` and `video_timestamp_seconds` set — these are the handoff fields the clip generation service reads.

### 7. Player box score

```bash
curl http://localhost:8000/games/1/stats/players
```

**Response (one entry per player):**
```json
[
  {
    "id": 1,
    "game_id": 1,
    "player_id": 1,
    "team_id": "lakers",
    "points": 5,
    "field_goals_made": 2,
    "field_goals_attempted": 2,
    "two_point_made": 1,
    "two_point_attempted": 1,
    "three_point_made": 1,
    "three_point_attempted": 1,
    "free_throws_made": 0,
    "free_throws_attempted": 0,
    "rebounds_offensive": 0,
    "rebounds_defensive": 0,
    "rebounds_total": 0,
    "assists": 0,
    "steals": 0,
    "blocks": 0,
    "turnovers": 0,
    "fouls": 1,
    "plus_minus": 0,
    "seconds_played": 0,
    "is_on_court": false,
    "points_by_period": {"Q1": 2, "Q2": 3},
    "field_goal_percentage": 100.0,
    "fg_pct": 100.0,
    "three_pt_pct": 100.0,
    "ft_pct": null,
    "ts_pct": 113.6,
    "efg_pct": 125.0
  }
]
```

### 8. Team stats and season aggregates

```bash
curl http://localhost:8000/games/1/stats/teams
```

**Season stats with advanced metrics (ORtg, DRtg, pace):**
```bash
curl http://localhost:8000/teams/lakers/season-stats
```

**Response:**
```json
{
  "team_id": "lakers",
  "games_played": 1,
  "wins": 1,
  "losses": 0,
  "points": 5,
  "rebounds": 0,
  "assists": 1,
  "steals": 0,
  "blocks": 0,
  "turnovers": 0,
  "fg_pct": 100.0,
  "three_pt_pct": 100.0,
  "ts_pct": 113.6,
  "efg_pct": 125.0,
  "ortg": 227.3,
  "drtg": null,
  "pace": 2.2
}
```

### 9. Player season stats with PLAi Score

**LeBron's season stats:**
```bash
curl http://localhost:8000/players/1/season-stats
```

**Response:**
```json
{
  "player_id": 1,
  "team_id": "lakers",
  "games_played": 1,
  "points": 5,
  "rebounds": 0,
  "assists": 0,
  "three_point_made": 1,
  "steals": 0,
  "blocks": 0,
  "turnovers": 0,
  "fg_pct": 100.0,
  "three_pt_pct": 100.0,
  "ft_pct": null,
  "ts_pct": 113.6,
  "efg_pct": 125.0,
  "plai_score": 62.5
}
```

The `plai_score` (0–100) measures a player's per-game contribution relative to their team — useful for ranking and scouting.

### 10. Shot chart data

**LeBron's shot chart:**
```bash
curl "http://localhost:8000/games/1/shot-chart?player_id=1"
```

**Response:**
```json
{
  "shots": [
    {
      "event_id": 1,
      "player_id": 1,
      "team_id": "lakers",
      "period": "Q1",
      "game_clock_seconds": 420,
      "shot_type": "TWO_POINT",
      "event_type": "SHOT_MADE",
      "court_x": 12.5,
      "court_y": 8.0
    }
  ],
  "total_made": 1,
  "total_attempted": 1,
  "fg_pct": 100.0
}
```

`court_x` and `court_y` are in feet — ready for overlay on a court diagram.

### Input Format Summary

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string enum | `SHOT_MADE`, `SHOT_MISSED`, `FOUL`, `SUBSTITUTION`, `TIMEOUT`, `TURNOVER`, `REBOUND`, `STEAL`, `BLOCK`, `ASSIST`, `GAME_START`, `GAME_END` |
| `period` | string enum | `Q1`, `Q2`, `Q3`, `Q4`, `OT1`, `OT2` |
| `game_clock_seconds` | integer | Seconds remaining in the period (e.g. 420 = 7:00 left) |
| `shot_type` | string enum | `TWO_POINT`, `THREE_POINT`, `FREE_THROW` (required for shot events) |
| `confidence` | float 0.0–1.0 | 1.0 for manual tags, lower for AI-detected events |
| `camera_id` + `video_timestamp_seconds` | string + float | Links event to raw footage for clip generation |
| `player_id` / `second_player_id` | integer | Two-player events: assist (passer + scorer), substitution (out + in) |

### Validation Rules

- `shot_type` is **required** for `SHOT_MADE`/`SHOT_MISSED`, **rejected** for other event types
- `ASSIST` and `SUBSTITUTION` require both `player_id` and `second_player_id`
- `FOUL`, `STEAL`, `BLOCK`, `TURNOVER`, `REBOUND` require `player_id`
- `team_id` must match one of the game's `home_team_id` or `away_team_id`
- `confidence` must be between 0.0 and 1.0
- `game_clock_seconds` must be >= 0

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
