from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    Enum,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base, engine
from enums import EventType, Period, ShotType


# --- SQLAlchemy Models ---

# Single game between 2 teams
class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)              # e.g. "Lakers vs Celtics - Week 3"
    home_team_id = Column(String, nullable=False)
    away_team_id = Column(String, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    events = relationship("GameEvent", back_populates="game")

# Single player
class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    team_id = Column(String, nullable=False)
    jersey_number = Column(String, nullable=True)


class GameEvent(Base):

    __tablename__ = "game_events"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    event_type = Column(Enum(EventType), nullable=False)
    period = Column(Enum(Period), nullable=False)
    game_clock_seconds = Column(Integer, nullable=False)       # seconds remaining in period
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    second_player_id = Column(Integer, nullable=True)           # e.g. scorer on an assist, entering player on a sub
    team_id = Column(String, nullable=False)                   # team with possession / responsible for event
    camera_id = Column(String, nullable=True)                  # which camera captured this moment
    video_timestamp_seconds = Column(Float, nullable=True)     # exact second in raw video file
    confidence = Column(Float, default=1.0)                    # 0.0-1.0, for AI-assisted tagging
    shot_type = Column(Enum(ShotType), nullable=True)          # only set for SHOT_MADE / SHOT_MISSED
    court_x = Column(Float, nullable=True)                     # x position on court (0-50 feet)
    court_y = Column(Float, nullable=True)                     # y position on court (0-47 feet)
    home_score_after = Column(Integer, nullable=True)          # score snapshot at this moment
    away_score_after = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="events")

    # Composite indexes for common query patterns
    __table_args__ = (
        Index("ix_game_events_timeline", "game_id", "period", "game_clock_seconds"),  # timeline/rebuild ordering
        Index("ix_game_events_type", "game_id", "event_type"),                        # filter by event type
        Index("ix_game_events_player", "game_id", "player_id"),                       # player-scoped queries
        Index("ix_game_events_player_camera", "player_id", "camera_id"),              # player highlight clips
    )


class PlayerGameStats(Base):
    """
    Denormalized player box score — one row per player per game.

    Updated incrementally each time an event is created. Can be wiped
    and rebuilt from events via the rebuild endpoint. This avoids
    expensive re-aggregation on every dashboard read.
    """
    __tablename__ = "player_game_stats"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    team_id = Column(String, nullable=False)

    # Scoring — FG counts exclude free throws (standard basketball convention)
    points = Column(Integer, default=0)
    field_goals_made = Column(Integer, default=0)
    field_goals_attempted = Column(Integer, default=0)
    two_point_made = Column(Integer, default=0)
    two_point_attempted = Column(Integer, default=0)
    three_point_made = Column(Integer, default=0)
    three_point_attempted = Column(Integer, default=0)
    free_throws_made = Column(Integer, default=0)
    free_throws_attempted = Column(Integer, default=0)

    # Box score
    rebounds_offensive = Column(Integer, default=0)     # same team missed the shot
    rebounds_defensive = Column(Integer, default=0)     # opposing team missed the shot
    rebounds_total = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    steals = Column(Integer, default=0)
    blocks = Column(Integer, default=0)
    turnovers = Column(Integer, default=0)
    fouls = Column(Integer, default=0)

    # Plus/minus: net score delta while this player is on court
    plus_minus = Column(Integer, default=0)
    seconds_played = Column(Integer, default=0)
    is_on_court = Column(Boolean, default=False)        # toggled by SUBSTITUTION events
    last_sub_clock = Column(Integer, nullable=True)     # game clock when last subbed in/out
    last_sub_period = Column(String, nullable=True)     # period when last subbed in/out

    # Shooting splits — stored as JSON string, e.g. {"Q1": 5, "Q2": 3}
    points_by_period = Column(String, default="{}")

    # Meta
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_player_game_stats"),
    )


class TeamGameStats(Base):
    """
    Denormalized team box score — one row per team per game.

    Same scoring/box-score fields as PlayerGameStats, plus timeouts
    and per-period shooting breakdowns for broadcast-style displays.
    """
    __tablename__ = "team_game_stats"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    team_id = Column(String, nullable=False)

    # Scoring
    points = Column(Integer, default=0)
    field_goals_made = Column(Integer, default=0)
    field_goals_attempted = Column(Integer, default=0)
    two_point_made = Column(Integer, default=0)
    two_point_attempted = Column(Integer, default=0)
    three_point_made = Column(Integer, default=0)
    three_point_attempted = Column(Integer, default=0)
    free_throws_made = Column(Integer, default=0)
    free_throws_attempted = Column(Integer, default=0)

    # Box score
    rebounds_offensive = Column(Integer, default=0)
    rebounds_defensive = Column(Integer, default=0)
    rebounds_total = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    steals = Column(Integer, default=0)
    blocks = Column(Integer, default=0)
    turnovers = Column(Integer, default=0)
    fouls = Column(Integer, default=0)
    timeouts = Column(Integer, default=0)               # team-only stat

    # Shooting splits by period — JSON strings, e.g. {"Q1": 4, "Q2": 6}
    points_by_period = Column(String, default="{}")
    fg_made_by_period = Column(String, default="{}")
    fg_attempted_by_period = Column(String, default="{}")

    # Meta
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_team_game_stats"),
    )


# --- Create tables ---
Base.metadata.create_all(bind=engine)
