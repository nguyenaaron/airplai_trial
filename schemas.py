import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field, model_validator

from enums import EventType, Period, ShotType


class GameCreate(BaseModel):
    name: str
    home_team_id: str
    away_team_id: str

    @model_validator(mode="after")
    def validate_game_fields(self):
        if not self.name or not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.home_team_id or not self.home_team_id.strip():
            raise ValueError("home_team_id must not be empty")
        if not self.away_team_id or not self.away_team_id.strip():
            raise ValueError("away_team_id must not be empty")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must be different")
        return self


class GameOut(BaseModel):
    id: int
    name: str
    home_team_id: str
    away_team_id: str
    date: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    event_type: EventType
    period: Period
    game_clock_seconds: int
    player_id: Optional[int] = None
    second_player_id: Optional[int] = None
    team_id: str
    camera_id: Optional[str] = None
    video_timestamp_seconds: Optional[float] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    shot_type: Optional[ShotType] = None
    court_x: Optional[float] = None
    court_y: Optional[float] = None
    home_score_after: Optional[int] = None
    away_score_after: Optional[int] = None

    @model_validator(mode="after")
    def validate_event_fields(self):
        if not self.team_id or not self.team_id.strip():
            raise ValueError("team_id must not be empty")
        if self.event_type in (EventType.SHOT_MADE, EventType.SHOT_MISSED):
            if self.shot_type is None:
                raise ValueError("shot_type is required for shot events")
        else:
            if self.shot_type is not None:
                raise ValueError("shot_type should only be set for shot events")
        if self.event_type in (EventType.SUBSTITUTION, EventType.ASSIST):
            if not self.player_id or not self.second_player_id:
                raise ValueError(f"{self.event_type.value} requires both player_id and second_player_id")
        if self.event_type in (EventType.FOUL, EventType.STEAL, EventType.BLOCK, EventType.TURNOVER, EventType.REBOUND):
            if not self.player_id:
                raise ValueError(f"{self.event_type.value} requires player_id")
        if self.game_clock_seconds < 0:
            raise ValueError("game_clock_seconds must be >= 0")
        return self


class EventUpdate(BaseModel):
    event_type: Optional[EventType] = None
    period: Optional[Period] = None
    game_clock_seconds: Optional[int] = None
    player_id: Optional[int] = None
    second_player_id: Optional[int] = None
    team_id: Optional[str] = None
    camera_id: Optional[str] = None
    video_timestamp_seconds: Optional[float] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    shot_type: Optional[ShotType] = None
    court_x: Optional[float] = None
    court_y: Optional[float] = None
    home_score_after: Optional[int] = None
    away_score_after: Optional[int] = None

    @model_validator(mode="after")
    def validate_update_fields(self):
        if self.team_id is not None and not self.team_id.strip():
            raise ValueError("team_id must not be empty")
        if self.game_clock_seconds is not None and self.game_clock_seconds < 0:
            raise ValueError("game_clock_seconds must be >= 0")
        return self


class EventOut(BaseModel):
    id: int
    game_id: int
    event_type: EventType
    period: Period
    game_clock_seconds: int
    player_id: Optional[int] = None
    second_player_id: Optional[int] = None
    team_id: str
    camera_id: Optional[str] = None
    video_timestamp_seconds: Optional[float] = None
    confidence: float
    shot_type: Optional[ShotType] = None
    court_x: Optional[float] = None
    court_y: Optional[float] = None
    home_score_after: Optional[int] = None
    away_score_after: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ShotChartEntryOut(BaseModel):
    event_id: int
    player_id: Optional[int] = None
    team_id: str
    period: Period
    game_clock_seconds: int
    shot_type: Optional[ShotType] = None
    event_type: EventType
    court_x: float
    court_y: float

    model_config = {"from_attributes": True}


class ShotChartOut(BaseModel):
    shots: list[ShotChartEntryOut]
    total_made: int
    total_attempted: int
    fg_pct: Optional[float] = None


class PlayerCreate(BaseModel):
    name: str
    team_id: str
    jersey_number: Optional[str] = None

    @model_validator(mode="after")
    def validate_player_fields(self):
        if not self.name or not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.team_id or not self.team_id.strip():
            raise ValueError("team_id must not be empty")
        return self


class PlayerOut(BaseModel):
    id: int
    name: str
    team_id: str
    jersey_number: Optional[str] = None

    model_config = {"from_attributes": True}


class PlayerGameStatsOut(BaseModel):
    """Response schema for player box scores. Includes a computed FG% field."""
    id: int
    game_id: int
    player_id: int
    team_id: str
    points: int
    field_goals_made: int
    field_goals_attempted: int
    two_point_made: int
    two_point_attempted: int
    three_point_made: int
    three_point_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    rebounds_offensive: int
    rebounds_defensive: int
    rebounds_total: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    plus_minus: int
    seconds_played: int
    is_on_court: bool
    points_by_period: dict = {}
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def field_goal_percentage(self) -> Optional[float]:
        if self.field_goals_attempted == 0:
            return None
        return round(self.field_goals_made / self.field_goals_attempted * 100, 1)

    @computed_field
    @property
    def fg_pct(self) -> Optional[float]:
        if self.field_goals_attempted == 0:
            return None
        return round(self.field_goals_made / self.field_goals_attempted * 100, 1)

    @computed_field
    @property
    def three_pt_pct(self) -> Optional[float]:
        if self.three_point_attempted == 0:
            return None
        return round(self.three_point_made / self.three_point_attempted * 100, 1)

    @computed_field
    @property
    def ft_pct(self) -> Optional[float]:
        if self.free_throws_attempted == 0:
            return None
        return round(self.free_throws_made / self.free_throws_attempted * 100, 1)

    @computed_field
    @property
    def ts_pct(self) -> Optional[float]:
        denom = 2 * (self.field_goals_attempted + 0.44 * self.free_throws_attempted)
        if denom == 0:
            return None
        return round(self.points / denom * 100, 1)

    @computed_field
    @property
    def efg_pct(self) -> Optional[float]:
        if self.field_goals_attempted == 0:
            return None
        return round((self.field_goals_made + 0.5 * self.three_point_made) / self.field_goals_attempted * 100, 1)

    @classmethod
    def from_orm_with_json(cls, obj):
        """Convert ORM object to schema, parsing JSON string fields into dicts."""
        data = {c.key: getattr(obj, c.key) for c in obj.__table__.columns}
        data["points_by_period"] = json.loads(data.get("points_by_period") or "{}")
        return cls(**data)


class TeamGameStatsOut(BaseModel):
    """Response schema for team box scores. Includes computed FG% and parsed period splits."""
    id: int
    game_id: int
    team_id: str
    points: int
    field_goals_made: int
    field_goals_attempted: int
    two_point_made: int
    two_point_attempted: int
    three_point_made: int
    three_point_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    rebounds_offensive: int
    rebounds_defensive: int
    rebounds_total: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    timeouts: int
    points_by_period: dict = {}
    fg_made_by_period: dict = {}
    fg_attempted_by_period: dict = {}
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def field_goal_percentage(self) -> Optional[float]:
        if self.field_goals_attempted == 0:
            return None
        return round(self.field_goals_made / self.field_goals_attempted * 100, 1)

    @computed_field
    @property
    def fg_pct(self) -> Optional[float]:
        if self.field_goals_attempted == 0:
            return None
        return round(self.field_goals_made / self.field_goals_attempted * 100, 1)

    @computed_field
    @property
    def three_pt_pct(self) -> Optional[float]:
        if self.three_point_attempted == 0:
            return None
        return round(self.three_point_made / self.three_point_attempted * 100, 1)

    @computed_field
    @property
    def ts_pct(self) -> Optional[float]:
        denom = 2 * (self.field_goals_attempted + 0.44 * self.free_throws_attempted)
        if denom == 0:
            return None
        return round(self.points / denom * 100, 1)

    @computed_field
    @property
    def efg_pct(self) -> Optional[float]:
        if self.field_goals_attempted == 0:
            return None
        return round((self.field_goals_made + 0.5 * self.three_point_made) / self.field_goals_attempted * 100, 1)

    @classmethod
    def from_orm_with_json(cls, obj):
        """Convert ORM object to schema, parsing JSON string fields into dicts."""
        data = {c.key: getattr(obj, c.key) for c in obj.__table__.columns}
        data["points_by_period"] = json.loads(data.get("points_by_period") or "{}")
        data["fg_made_by_period"] = json.loads(data.get("fg_made_by_period") or "{}")
        data["fg_attempted_by_period"] = json.loads(data.get("fg_attempted_by_period") or "{}")
        return cls(**data)


class PlayerSeasonStatsOut(BaseModel):
    """Aggregated player stats across all games."""
    player_id: int
    team_id: str
    games_played: int
    points: int
    rebounds: int
    assists: int
    three_point_made: int
    steals: int
    blocks: int
    turnovers: int
    fg_pct: Optional[float] = None
    three_pt_pct: Optional[float] = None
    ft_pct: Optional[float] = None
    ts_pct: Optional[float] = None
    efg_pct: Optional[float] = None
    plai_score: Optional[float] = None


class TeamSeasonStatsOut(BaseModel):
    """Aggregated team stats across all games."""
    team_id: str
    games_played: int
    wins: int
    losses: int
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fg_pct: Optional[float] = None
    three_pt_pct: Optional[float] = None
    ts_pct: Optional[float] = None
    efg_pct: Optional[float] = None
    ortg: Optional[float] = None
    drtg: Optional[float] = None
    pace: Optional[float] = None
