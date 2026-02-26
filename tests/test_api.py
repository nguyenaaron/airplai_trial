"""
Tests for the AirPLAi Event Tagging API.

Uses an in-memory-style SQLite database (test.db) that is created fresh
before each test and torn down after, ensuring test isolation.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from main import app
from database import Base, get_db

# Separate test database to avoid polluting the dev database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Swap the app's DB session with our test database session."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the app's get_db dependency so all requests use the test DB
app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test and drop them after for a clean slate."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_test_game():
    """Helper: create a standard test game (team_home vs team_away)."""
    return client.post("/games", json={
        "name": "Test Game",
        "home_team_id": "team_home",
        "away_team_id": "team_away",
    })


def create_test_player(name="Player 1", team_id="team_home", jersey_number=None):
    """Helper: create a player and return the response."""
    payload = {"name": name, "team_id": team_id}
    if jersey_number:
        payload["jersey_number"] = jersey_number
    resp = client.post("/players", json=payload)
    assert resp.status_code == 200
    return resp.json()


# ==================== Game CRUD tests ====================

def test_create_game():
    """POST /games should return the created game with an assigned ID."""
    response = create_test_game()
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Game"
    assert data["home_team_id"] == "team_home"
    assert data["away_team_id"] == "team_away"
    assert "id" in data


def test_get_game():
    """GET /games/{id} should return the game we just created."""
    create_resp = create_test_game()
    game_id = create_resp.json()["id"]
    response = client.get(f"/games/{game_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Game"


def test_get_game_not_found():
    """GET /games/{id} should 404 for a non-existent game."""
    response = client.get("/games/999")
    assert response.status_code == 404


# ==================== Event CRUD tests ====================

def test_create_event():
    """POST /games/{id}/events should create an event and return all fields."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    response = client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 420,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
        "confidence": 0.95,
        "home_score_after": 2,
        "away_score_after": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["event_type"] == "SHOT_MADE"
    assert data["period"] == "Q1"
    assert data["game_clock_seconds"] == 420
    assert data["confidence"] == 0.95


def test_create_event_game_not_found():
    """POST /games/{id}/events should 404 if the game doesn't exist."""
    p1 = create_test_player("Player 1", "team_away")
    response = client.post("/games/999/events", json={
        "event_type": "FOUL",
        "period": "Q2",
        "game_clock_seconds": 300,
        "team_id": "team_away",
        "player_id": p1["id"],
    })
    assert response.status_code == 404


def test_get_events_with_filters():
    """GET /games/{id}/events should support filtering by type, period, and player."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_away")
    client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
    })
    client.post(f"/games/{game_id}/events", json={
        "event_type": "FOUL",
        "period": "Q2",
        "game_clock_seconds": 300,
        "team_id": "team_away",
        "player_id": p2["id"],
    })

    # All events
    response = client.get(f"/games/{game_id}/events")
    assert len(response.json()) == 2

    # Filter by type
    response = client.get(f"/games/{game_id}/events?event_type=FOUL")
    assert len(response.json()) == 1
    assert response.json()[0]["event_type"] == "FOUL"

    # Filter by period
    response = client.get(f"/games/{game_id}/events?period=Q1")
    assert len(response.json()) == 1

    # Filter by player
    response = client.get(f"/games/{game_id}/events?player_id={p1['id']}")
    assert len(response.json()) == 1


def test_timeline():
    """GET /games/{id}/timeline should return events in chronological order (descending clock)."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    client.post(f"/games/{game_id}/events", json={
        "event_type": "GAME_START",
        "period": "Q1",
        "game_clock_seconds": 480,
        "team_id": "team_home",
    })
    client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 420,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
    })
    response = client.get(f"/games/{game_id}/timeline")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2
    assert events[0]["game_clock_seconds"] >= events[1]["game_clock_seconds"]


def test_highlights():
    """GET /games/{id}/highlights should only return events with camera data above confidence threshold."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_away")
    client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
        "camera_id": "cam_1",
        "video_timestamp_seconds": 120.5,
        "confidence": 0.9,
    })
    client.post(f"/games/{game_id}/events", json={
        "event_type": "FOUL",
        "period": "Q1",
        "game_clock_seconds": 350,
        "team_id": "team_away",
        "player_id": p2["id"],
    })

    response = client.get(f"/games/{game_id}/highlights")
    assert len(response.json()) == 1
    assert response.json()[0]["camera_id"] == "cam_1"

    response = client.get(f"/games/{game_id}/highlights?min_confidence=0.95")
    assert len(response.json()) == 0


def test_player_highlights():
    """GET /players/{id}/highlights should return clips for a specific player across games."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
        "camera_id": "cam_1",
        "video_timestamp_seconds": 120.5,
    })
    response = client.get(f"/players/{p1['id']}/highlights")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_two_player_event():
    """Events like assists use second_player_id for the second participant."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_home")
    response = client.post(f"/games/{game_id}/events", json={
        "event_type": "ASSIST",
        "period": "Q3",
        "game_clock_seconds": 200,
        "team_id": "team_home",
        "player_id": p1["id"],
        "second_player_id": p2["id"],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["second_player_id"] == p2["id"]


# ==================== Stats tests ====================
# These tests verify that the denormalized stats tables are correctly
# updated when events are created via POST /games/{id}/events.

def _post_event(game_id, **kwargs):
    """Helper: post an event with sensible defaults (Q1, 400s, team_home)."""
    payload = {
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        **kwargs,
    }
    resp = client.post(f"/games/{game_id}/events", json=payload)
    assert resp.status_code == 200, f"Event creation failed: {resp.json()}"
    return resp.json()


def test_shot_stats_update():
    """Test that player and team stats are updated after shot events."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    # Two-pointer made
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=450)
    # Three-pointer made
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400)
    # Two-pointer missed
    _post_event(game_id, event_type="SHOT_MISSED", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=350)
    # Free throw made
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="FREE_THROW", game_clock_seconds=300)

    # Check player stats
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.status_code == 200
    stats = resp.json()
    assert len(stats) == 1
    ps = stats[0]
    assert ps["player_id"] == pid
    assert ps["points"] == 6  # 2 + 3 + 1
    assert ps["field_goals_made"] == 2  # 2pt + 3pt (FT excluded)
    assert ps["field_goals_attempted"] == 3  # 2pt made + 3pt made + 2pt missed
    assert ps["two_point_made"] == 1
    assert ps["two_point_attempted"] == 2
    assert ps["three_point_made"] == 1
    assert ps["three_point_attempted"] == 1
    assert ps["free_throws_made"] == 1
    assert ps["free_throws_attempted"] == 1
    assert ps["field_goal_percentage"] == 66.7  # 2/3

    # Check team stats
    resp = client.get(f"/games/{game_id}/stats/teams")
    assert resp.status_code == 200
    tstats = resp.json()
    assert len(tstats) == 1
    ts = tstats[0]
    assert ts["points"] == 6
    assert ts["field_goals_made"] == 2
    assert ts["field_goals_attempted"] == 3
    assert ts["field_goal_percentage"] == 66.7


def test_shooting_splits_by_period():
    """Test that points_by_period is tracked correctly."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", period="Q1", game_clock_seconds=400)
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", period="Q2", game_clock_seconds=400)

    resp = client.get(f"/games/{game_id}/stats/players")
    ps = resp.json()[0]
    assert ps["points_by_period"]["Q1"] == 2
    assert ps["points_by_period"]["Q2"] == 3

    resp = client.get(f"/games/{game_id}/stats/teams")
    ts = resp.json()[0]
    assert ts["points_by_period"]["Q1"] == 2
    assert ts["points_by_period"]["Q2"] == 3
    assert ts["fg_made_by_period"]["Q1"] == 1
    assert ts["fg_made_by_period"]["Q2"] == 1


def test_rebound_classification():
    """Test offensive vs defensive rebound classification."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_home")
    p3 = create_test_player("Player 3", "team_away")

    # Shot missed by team_home
    _post_event(game_id, event_type="SHOT_MISSED", player_id=p1["id"],
                team_id="team_home", shot_type="TWO_POINT", game_clock_seconds=400)
    # Rebound by team_home → offensive
    _post_event(game_id, event_type="REBOUND", player_id=p2["id"],
                team_id="team_home", game_clock_seconds=398)
    # Shot missed by team_home
    _post_event(game_id, event_type="SHOT_MISSED", player_id=p1["id"],
                team_id="team_home", shot_type="TWO_POINT", game_clock_seconds=350)
    # Rebound by team_away → defensive
    _post_event(game_id, event_type="REBOUND", player_id=p3["id"],
                team_id="team_away", game_clock_seconds=348)

    resp = client.get(f"/games/{game_id}/stats/players")
    stats_by_player = {s["player_id"]: s for s in resp.json()}

    assert stats_by_player[p2["id"]]["rebounds_offensive"] == 1
    assert stats_by_player[p2["id"]]["rebounds_defensive"] == 0
    assert stats_by_player[p2["id"]]["rebounds_total"] == 1
    assert stats_by_player[p3["id"]]["rebounds_offensive"] == 0
    assert stats_by_player[p3["id"]]["rebounds_defensive"] == 1
    assert stats_by_player[p3["id"]]["rebounds_total"] == 1


def test_counter_stats():
    """Test assist, steal, block, turnover, foul counters."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_home")
    pid = p1["id"]

    _post_event(game_id, event_type="ASSIST", player_id=pid, second_player_id=p2["id"], game_clock_seconds=450)
    _post_event(game_id, event_type="STEAL", player_id=pid, game_clock_seconds=400)
    _post_event(game_id, event_type="BLOCK", player_id=pid, game_clock_seconds=350)
    _post_event(game_id, event_type="TURNOVER", player_id=pid, game_clock_seconds=300)
    _post_event(game_id, event_type="FOUL", player_id=pid, game_clock_seconds=250)

    resp = client.get(f"/games/{game_id}/stats/players")
    ps = resp.json()[0]
    assert ps["assists"] == 1
    assert ps["steals"] == 1
    assert ps["blocks"] == 1
    assert ps["turnovers"] == 1
    assert ps["fouls"] == 1

    resp = client.get(f"/games/{game_id}/stats/teams")
    ts = resp.json()[0]
    assert ts["assists"] == 1
    assert ts["steals"] == 1
    assert ts["blocks"] == 1
    assert ts["turnovers"] == 1
    assert ts["fouls"] == 1


def test_timeout_team_stats():
    """Test timeout increments team stats only."""
    game_id = create_test_game().json()["id"]

    _post_event(game_id, event_type="TIMEOUT", game_clock_seconds=400)

    resp = client.get(f"/games/{game_id}/stats/teams")
    ts = resp.json()[0]
    assert ts["timeouts"] == 1


def test_substitution_tracking():
    """Test that substitution updates is_on_court tracking."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_home")

    # p1 exits, p2 enters
    _post_event(game_id, event_type="SUBSTITUTION", player_id=p1["id"],
                second_player_id=p2["id"], game_clock_seconds=400)

    resp = client.get(f"/games/{game_id}/stats/players")
    stats_by_player = {s["player_id"]: s for s in resp.json()}
    assert stats_by_player[p1["id"]]["is_on_court"] is False
    assert stats_by_player[p2["id"]]["is_on_court"] is True


def test_substitution_seconds_played():
    """Test that seconds_played is calculated on substitution out."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p_bench = create_test_player("Bench Player", "team_home")

    # p1 enters at 480 (sub in)
    _post_event(game_id, event_type="SUBSTITUTION", player_id=p_bench["id"],
                second_player_id=p1["id"], game_clock_seconds=480, period="Q1")
    # p1 exits at 400 (sub out) → 80 seconds played
    _post_event(game_id, event_type="SUBSTITUTION", player_id=p1["id"],
                second_player_id=p_bench["id"], game_clock_seconds=400, period="Q1")

    resp = client.get(f"/games/{game_id}/stats/players")
    stats_by_player = {s["player_id"]: s for s in resp.json()}
    assert stats_by_player[p1["id"]]["seconds_played"] == 80
    assert stats_by_player[p1["id"]]["is_on_court"] is False


def test_plus_minus():
    """Test plus/minus updates for on-court players during scoring."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_away")
    p_bench = create_test_player("Bench Home", "team_home")
    p_bench2 = create_test_player("Bench Away", "team_away")

    # Sub p1 onto court for team_home
    _post_event(game_id, event_type="SUBSTITUTION", player_id=p_bench["id"],
                second_player_id=p1["id"], team_id="team_home", game_clock_seconds=480)
    # Sub p2 onto court for team_away
    _post_event(game_id, event_type="SUBSTITUTION", player_id=p_bench2["id"],
                second_player_id=p2["id"], team_id="team_away", game_clock_seconds=480)

    # team_home scores 2 points
    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                team_id="team_home", shot_type="TWO_POINT", game_clock_seconds=450)

    resp = client.get(f"/games/{game_id}/stats/players")
    stats_by_player = {s["player_id"]: s for s in resp.json()}
    assert stats_by_player[p1["id"]]["plus_minus"] == 2
    assert stats_by_player[p2["id"]]["plus_minus"] == -2


def test_stats_rebuild():
    """Test that rebuild endpoint recalculates stats from events."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=450)
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400)

    # Verify initial stats
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.json()[0]["points"] == 5

    # Rebuild
    resp = client.post(f"/games/{game_id}/stats/rebuild")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify stats are the same after rebuild
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.json()[0]["points"] == 5
    assert resp.json()[0]["field_goals_made"] == 2


def test_player_stats_across_games():
    """Test GET /players/{player_id}/stats returns stats across games."""
    game1 = create_test_game().json()["id"]
    game2 = client.post("/games", json={
        "name": "Game 2", "home_team_id": "team_home", "away_team_id": "team_away",
    }).json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    _post_event(game1, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=400)
    _post_event(game2, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400)

    # All games
    resp = client.get(f"/players/{pid}/stats")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # Filtered to one game
    resp = client.get(f"/players/{pid}/stats?game_id={game1}")
    assert len(resp.json()) == 1
    assert resp.json()[0]["points"] == 2


def test_stats_game_not_found():
    """Test 404 on stats endpoints for non-existent game."""
    resp = client.get("/games/999/stats/players")
    assert resp.status_code == 404
    resp = client.get("/games/999/stats/teams")
    assert resp.status_code == 404
    resp = client.post("/games/999/stats/rebuild")
    assert resp.status_code == 404


def test_shot_type_in_event():
    """Test that shot_type is stored and returned in event responses."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    resp = _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                       shot_type="THREE_POINT", game_clock_seconds=400)
    assert resp["shot_type"] == "THREE_POINT"


# ==================== Validation tests ====================

def test_validation_shot_requires_shot_type():
    """SHOT_MADE without shot_type should return 422."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": p1["id"],
    })
    assert resp.status_code == 422


def test_validation_foul_requires_player_id():
    """FOUL without player_id should return 422."""
    game_id = create_test_game().json()["id"]
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "FOUL",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
    })
    assert resp.status_code == 422


def test_validation_substitution_requires_second_player():
    """SUBSTITUTION without second_player_id should return 422."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "SUBSTITUTION",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": p1["id"],
    })
    assert resp.status_code == 422


def test_validation_shot_type_on_non_shot_rejected():
    """shot_type on a non-shot event should return 422."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "FOUL",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
    })
    assert resp.status_code == 422


def test_validation_negative_game_clock():
    """Negative game_clock_seconds should return 422."""
    game_id = create_test_game().json()["id"]
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "TIMEOUT",
        "period": "Q1",
        "game_clock_seconds": -1,
        "team_id": "team_home",
    })
    assert resp.status_code == 422


# ==================== New validation tests ====================

def test_create_game_same_teams():
    """422 when home_team_id == away_team_id."""
    resp = client.post("/games", json={
        "name": "Bad Game",
        "home_team_id": "team_a",
        "away_team_id": "team_a",
    })
    assert resp.status_code == 422


def test_event_invalid_team_id():
    """422 when team_id isn't home or away."""
    game_id = create_test_game().json()["id"]
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "TIMEOUT",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_random",
    })
    assert resp.status_code == 422


def test_empty_string_rejection():
    """422 for empty name/team_id on games and players."""
    # Empty game name
    resp = client.post("/games", json={
        "name": "",
        "home_team_id": "team_home",
        "away_team_id": "team_away",
    })
    assert resp.status_code == 422

    # Empty home_team_id
    resp = client.post("/games", json={
        "name": "Test",
        "home_team_id": "",
        "away_team_id": "team_away",
    })
    assert resp.status_code == 422

    # Empty player name
    resp = client.post("/players", json={
        "name": "",
        "team_id": "team_home",
    })
    assert resp.status_code == 422

    # Empty player team_id
    resp = client.post("/players", json={
        "name": "Player 1",
        "team_id": "",
    })
    assert resp.status_code == 422

    # Empty event team_id
    game_id = create_test_game().json()["id"]
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "TIMEOUT",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "",
    })
    assert resp.status_code == 422


# ==================== DELETE / PATCH tests ====================

def test_delete_event():
    """DELETE removes event and recalculates stats."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    # Create two shot events
    e1 = _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                     shot_type="TWO_POINT", game_clock_seconds=450)
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400)

    # Verify 5 points
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.json()[0]["points"] == 5

    # Delete first event (2-pointer)
    resp = client.delete(f"/games/{game_id}/events/{e1['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Verify stats recalculated to 3 points
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.json()[0]["points"] == 3

    # Verify event is gone
    resp = client.get(f"/games/{game_id}/events")
    assert len(resp.json()) == 1


def test_delete_event_not_found():
    """404 for non-existent event."""
    game_id = create_test_game().json()["id"]
    resp = client.delete(f"/games/{game_id}/events/999")
    assert resp.status_code == 404


def test_patch_event():
    """PATCH updates fields and recalculates stats."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    e1 = _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                     shot_type="TWO_POINT", game_clock_seconds=450)

    # Verify 2 points
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.json()[0]["points"] == 2

    # Patch to three-pointer
    resp = client.patch(f"/games/{game_id}/events/{e1['id']}", json={
        "shot_type": "THREE_POINT",
    })
    assert resp.status_code == 200
    assert resp.json()["shot_type"] == "THREE_POINT"

    # Verify stats recalculated to 3 points
    resp = client.get(f"/games/{game_id}/stats/players")
    assert resp.json()[0]["points"] == 3


def test_patch_event_not_found():
    """404 for non-existent event."""
    game_id = create_test_game().json()["id"]
    resp = client.patch(f"/games/{game_id}/events/999", json={
        "game_clock_seconds": 100,
    })
    assert resp.status_code == 404


# ==================== Computed percentage tests ====================

def test_computed_percentages_player():
    """Test TS%, eFG%, 3PT%, FT% on player game stats."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    # 2pt made, 3pt made, 2pt missed, FT made
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=450)
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400)
    _post_event(game_id, event_type="SHOT_MISSED", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=350)
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="FREE_THROW", game_clock_seconds=300)

    resp = client.get(f"/games/{game_id}/stats/players")
    ps = resp.json()[0]
    # FGM=2, FGA=3, 3PM=1, 3PA=1, FTM=1, FTA=1, PTS=6
    assert ps["fg_pct"] == 66.7          # 2/3 * 100
    assert ps["three_pt_pct"] == 100.0   # 1/1 * 100
    assert ps["ft_pct"] == 100.0         # 1/1 * 100
    # TS% = 6 / (2 * (3 + 0.44*1)) * 100 = 6 / 6.88 * 100 = 87.2
    assert ps["ts_pct"] == 87.2
    # eFG% = (2 + 0.5*1) / 3 * 100 = 83.3
    assert ps["efg_pct"] == 83.3


def test_computed_percentages_team():
    """Test TS%, eFG%, 3PT% on team game stats."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    pid = p1["id"]

    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=450)
    _post_event(game_id, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400)

    resp = client.get(f"/games/{game_id}/stats/teams")
    ts = resp.json()[0]
    # FGM=2, FGA=2, 3PM=1, PTS=5
    assert ts["fg_pct"] == 100.0
    assert ts["three_pt_pct"] == 100.0
    # TS% = 5 / (2 * 2) * 100 = 125.0
    assert ts["ts_pct"] == 125.0
    # eFG% = (2 + 0.5) / 2 * 100 = 125.0
    assert ts["efg_pct"] == 125.0


def test_computed_percentages_zero_attempts():
    """Computed percentages should be None when no attempts."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")

    _post_event(game_id, event_type="STEAL", player_id=p1["id"], game_clock_seconds=400)

    resp = client.get(f"/games/{game_id}/stats/players")
    ps = resp.json()[0]
    assert ps["fg_pct"] is None
    assert ps["three_pt_pct"] is None
    assert ps["ft_pct"] is None
    assert ps["ts_pct"] is None
    assert ps["efg_pct"] is None


# ==================== Season stats tests ====================

def _create_two_game_setup():
    """Helper: create 2 games with events for season stats testing.

    Returns (game1_id, game2_id, player_id).
    Game 1: team_home wins (player scores 5 pts: 2pt + 3pt)
    Game 2: team_away wins (player scores 3 pts: 3pt, and a steal + assist)
    """
    g1 = create_test_game().json()["id"]
    g2 = client.post("/games", json={
        "name": "Game 2", "home_team_id": "team_home", "away_team_id": "team_away",
    }).json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_home")
    p3 = create_test_player("Opp Player", "team_away")
    pid = p1["id"]

    # Game 1: team_home scores 5 (2pt + 3pt), team_away scores 2
    _post_event(g1, event_type="SHOT_MADE", player_id=pid,
                shot_type="TWO_POINT", game_clock_seconds=450, team_id="team_home")
    _post_event(g1, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=400, team_id="team_home")
    _post_event(g1, event_type="SHOT_MADE", player_id=p3["id"],
                shot_type="TWO_POINT", game_clock_seconds=380, team_id="team_away")

    # Game 2: team_home scores 3 (3pt), team_away scores 5
    _post_event(g2, event_type="SHOT_MADE", player_id=pid,
                shot_type="THREE_POINT", game_clock_seconds=450, team_id="team_home")
    _post_event(g2, event_type="STEAL", player_id=pid,
                game_clock_seconds=400, team_id="team_home")
    _post_event(g2, event_type="ASSIST", player_id=pid, second_player_id=p2["id"],
                game_clock_seconds=380, team_id="team_home")
    _post_event(g2, event_type="SHOT_MADE", player_id=p3["id"],
                shot_type="TWO_POINT", game_clock_seconds=350, team_id="team_away")
    _post_event(g2, event_type="SHOT_MADE", player_id=p3["id"],
                shot_type="THREE_POINT", game_clock_seconds=300, team_id="team_away")

    return g1, g2, pid


def test_player_season_stats():
    """Test aggregated player season stats endpoint."""
    g1, g2, pid = _create_two_game_setup()

    resp = client.get(f"/players/{pid}/season-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_id"] == pid
    assert data["games_played"] == 2
    assert data["points"] == 8     # 5 + 3
    assert data["assists"] == 1
    assert data["steals"] == 1
    assert data["three_point_made"] == 2  # 1 + 1
    # FGM=3 (2pt + 3pt + 3pt), FGA=3
    assert data["fg_pct"] == 100.0
    assert data["three_pt_pct"] == 100.0


def test_player_season_stats_not_found():
    """404 for player with no stats."""
    resp = client.get("/players/99999/season-stats")
    assert resp.status_code == 404


def test_team_season_stats():
    """Test aggregated team season stats including W/L."""
    g1, g2, pid = _create_two_game_setup()

    resp = client.get("/teams/team_home/season-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["team_id"] == "team_home"
    assert data["games_played"] == 2
    assert data["wins"] == 1       # won game 1 (5 vs 2)
    assert data["losses"] == 1     # lost game 2 (3 vs 5)
    assert data["points"] == 8     # 5 + 3
    assert data["assists"] == 1
    assert data["steals"] == 1
    assert data["fg_pct"] == 100.0  # 3/3


def test_team_season_stats_drtg():
    """Test DRtg computation (opponent points / possessions * 100)."""
    g1, g2, pid = _create_two_game_setup()

    resp = client.get("/teams/team_home/season-stats")
    data = resp.json()
    # team_home: FGA=3, OREB=0, TOV=0, FTA=0 → poss=3
    # opponent scored 7 total (2 + 5)
    # DRtg = 7 / 3 * 100 = 233.3
    assert data["drtg"] == 233.3
    assert data["ortg"] is not None
    assert data["pace"] is not None


def test_team_season_stats_not_found():
    """404 for team with no stats."""
    resp = client.get("/teams/nonexistent/season-stats")
    assert resp.status_code == 404


def test_plai_score():
    """Test PLAi Score is computed and within expected range."""
    g1, g2, pid = _create_two_game_setup()

    resp = client.get(f"/players/{pid}/season-stats")
    data = resp.json()
    assert data["plai_score"] is not None
    assert data["plai_score"] > 0
    assert data["plai_score"] <= 100


# ==================== Shot chart tests ====================

def test_shot_chart_basic():
    """Shot chart returns shots with coordinates and correct summary stats."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")

    # Shot with coordinates (made)
    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                shot_type="TWO_POINT", game_clock_seconds=450,
                court_x=25.0, court_y=10.0)
    # Shot with coordinates (missed)
    _post_event(game_id, event_type="SHOT_MISSED", player_id=p1["id"],
                shot_type="THREE_POINT", game_clock_seconds=400,
                court_x=30.0, court_y=25.0)

    resp = client.get(f"/games/{game_id}/shot-chart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_attempted"] == 2
    assert data["total_made"] == 1
    assert data["fg_pct"] == 50.0
    assert len(data["shots"]) == 2
    # Verify coordinate data is present
    assert data["shots"][0]["court_x"] == 25.0
    assert data["shots"][0]["court_y"] == 10.0


def test_shot_chart_excludes_no_coordinates():
    """Shots without court_x/court_y are excluded from shot chart."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")

    # Shot WITH coordinates
    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                shot_type="TWO_POINT", game_clock_seconds=450,
                court_x=25.0, court_y=10.0)
    # Shot WITHOUT coordinates
    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                shot_type="FREE_THROW", game_clock_seconds=400)

    resp = client.get(f"/games/{game_id}/shot-chart")
    data = resp.json()
    assert len(data["shots"]) == 1
    assert data["total_attempted"] == 1


def test_shot_chart_filter_by_player():
    """Shot chart filters by player_id."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_away")

    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                shot_type="TWO_POINT", game_clock_seconds=450,
                team_id="team_home", court_x=10.0, court_y=5.0)
    _post_event(game_id, event_type="SHOT_MISSED", player_id=p2["id"],
                shot_type="THREE_POINT", game_clock_seconds=400,
                team_id="team_away", court_x=35.0, court_y=25.0)

    resp = client.get(f"/games/{game_id}/shot-chart?player_id={p1['id']}")
    data = resp.json()
    assert len(data["shots"]) == 1
    assert data["shots"][0]["player_id"] == p1["id"]


def test_shot_chart_filter_by_team():
    """Shot chart filters by team_id."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")
    p2 = create_test_player("Player 2", "team_away")

    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                shot_type="TWO_POINT", game_clock_seconds=450,
                team_id="team_home", court_x=10.0, court_y=5.0)
    _post_event(game_id, event_type="SHOT_MISSED", player_id=p2["id"],
                shot_type="THREE_POINT", game_clock_seconds=400,
                team_id="team_away", court_x=35.0, court_y=25.0)

    resp = client.get(f"/games/{game_id}/shot-chart?team_id=team_away")
    data = resp.json()
    assert len(data["shots"]) == 1
    assert data["shots"][0]["team_id"] == "team_away"


def test_shot_chart_filter_by_period():
    """Shot chart filters by period."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")

    _post_event(game_id, event_type="SHOT_MADE", player_id=p1["id"],
                shot_type="TWO_POINT", period="Q1", game_clock_seconds=450,
                court_x=10.0, court_y=5.0)
    _post_event(game_id, event_type="SHOT_MISSED", player_id=p1["id"],
                shot_type="THREE_POINT", period="Q2", game_clock_seconds=400,
                court_x=35.0, court_y=25.0)

    resp = client.get(f"/games/{game_id}/shot-chart?period=Q1")
    data = resp.json()
    assert len(data["shots"]) == 1
    assert data["shots"][0]["period"] == "Q1"


def test_shot_chart_game_not_found():
    """404 for non-existent game."""
    resp = client.get("/games/999/shot-chart")
    assert resp.status_code == 404


def test_shot_chart_empty():
    """Empty shot chart returns zero stats and null fg_pct."""
    game_id = create_test_game().json()["id"]

    resp = client.get(f"/games/{game_id}/shot-chart")
    data = resp.json()
    assert len(data["shots"]) == 0
    assert data["total_made"] == 0
    assert data["total_attempted"] == 0
    assert data["fg_pct"] is None


def test_create_event_with_coordinates():
    """Events can be created with court_x/court_y and they appear in EventOut."""
    game_id = create_test_game().json()["id"]
    p1 = create_test_player("Player 1", "team_home")

    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "SHOT_MADE",
        "period": "Q1",
        "game_clock_seconds": 420,
        "team_id": "team_home",
        "player_id": p1["id"],
        "shot_type": "TWO_POINT",
        "court_x": 25.5,
        "court_y": 12.3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["court_x"] == 25.5
    assert data["court_y"] == 12.3


def test_foreign_key_enforcement():
    """Creating event with non-existent player_id should fail."""
    game_id = create_test_game().json()["id"]
    resp = client.post(f"/games/{game_id}/events", json={
        "event_type": "FOUL",
        "period": "Q1",
        "game_clock_seconds": 400,
        "team_id": "team_home",
        "player_id": 99999,
    })
    assert resp.status_code == 500 or resp.status_code == 422
