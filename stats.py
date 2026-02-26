import enum
import json
from typing import Optional

from sqlalchemy.orm import Session

from enums import EventType, Period, ShotType
from models import Game, GameEvent, PlayerGameStats, TeamGameStats


# --- Stats helper functions ---
# Stats are denormalized: updated incrementally on every event insert.
# This trades write-time cost for instant reads on dashboards/APIs.

def get_or_create_player_stats(db: Session, game_id: int, player_id: str, team_id: str) -> PlayerGameStats:
    """Fetch existing stats row or create a zeroed-out one for this player+game."""
    stats = db.query(PlayerGameStats).filter(
        PlayerGameStats.game_id == game_id,
        PlayerGameStats.player_id == player_id,
    ).first()
    if not stats:
        stats = PlayerGameStats(game_id=game_id, player_id=player_id, team_id=team_id)
        db.add(stats)
        db.flush()
    return stats


def get_or_create_team_stats(db: Session, game_id: int, team_id: str) -> TeamGameStats:
    """Fetch existing stats row or create a zeroed-out one for this team+game."""
    stats = db.query(TeamGameStats).filter(
        TeamGameStats.game_id == game_id,
        TeamGameStats.team_id == team_id,
    ).first()
    if not stats:
        stats = TeamGameStats(game_id=game_id, team_id=team_id)
        db.add(stats)
        db.flush()
    return stats


def _increment_json_period(json_str: str, period: str, amount: int) -> str:
    """Add `amount` to a period key in a JSON-encoded dict string."""
    data = json.loads(json_str or "{}")
    data[period] = data.get(period, 0) + amount
    return json.dumps(data)


def _points_for_shot(shot_type: Optional[ShotType]) -> int:
    """Return point value for a made shot. Defaults to 2 if shot_type is unset."""
    if shot_type == ShotType.THREE_POINT:
        return 3
    elif shot_type == ShotType.FREE_THROW:
        return 1
    return 2  # default TWO_POINT or unspecified


def _update_plus_minus(db: Session, game_id: int, team_id: str, score_delta: int, game: Game):
    """Update plus/minus for all on-court players when a score happens."""
    if score_delta == 0:
        return
    if team_id not in (game.home_team_id, game.away_team_id):
        return
    # Players on the scoring team get +delta
    scoring_players = db.query(PlayerGameStats).filter(
        PlayerGameStats.game_id == game_id,
        PlayerGameStats.team_id == team_id,
        PlayerGameStats.is_on_court == True,
    ).all()
    for p in scoring_players:
        p.plus_minus += score_delta

    # Players on the opposing team get -delta
    opposing_team_id = game.away_team_id if team_id == game.home_team_id else game.home_team_id
    opposing_players = db.query(PlayerGameStats).filter(
        PlayerGameStats.game_id == game_id,
        PlayerGameStats.team_id == opposing_team_id,
        PlayerGameStats.is_on_court == True,
    ).all()
    for p in opposing_players:
        p.plus_minus -= score_delta


# Maps periods to sequential indices for elapsed-time calculations across periods.
PERIOD_ORDER = {Period.Q1: 0, Period.Q2: 1, Period.Q3: 2, Period.Q4: 3, Period.OT1: 4, Period.OT2: 5}


def _calc_elapsed_seconds(from_period: str, from_clock: int, to_period: str, to_clock: int) -> int:
    """Calculate elapsed game seconds between two game clock readings.
    Game clock counts DOWN, so earlier events have higher clock values.
    """
    from_idx = PERIOD_ORDER.get(from_period, 0)
    to_idx = PERIOD_ORDER.get(to_period, 0)
    if from_idx == to_idx:
        return max(0, from_clock - to_clock)
    # Cross-period: assume 480 second periods (8 min youth basketball)
    period_length = 480
    elapsed = from_clock  # remaining in the starting period
    elapsed += (to_idx - from_idx - 1) * period_length  # full periods in between
    elapsed += (period_length - to_clock)  # elapsed in the destination period
    return max(0, elapsed)


def _apply_shot_stats(stats, shot_type: Optional[ShotType], made: bool, pts: int, period: str):
    """Update shooting counters on a stats object (player or team)."""
    if shot_type == ShotType.FREE_THROW:
        stats.free_throws_attempted += 1
        if made:
            stats.free_throws_made += 1
    else:
        stats.field_goals_attempted += 1
        if shot_type == ShotType.THREE_POINT:
            stats.three_point_attempted += 1
            if made:
                stats.three_point_made += 1
        else:  # TWO_POINT or None
            stats.two_point_attempted += 1
            if made:
                stats.two_point_made += 1
        if made:
            stats.field_goals_made += 1
    if made:
        stats.points += pts
        stats.points_by_period = _increment_json_period(stats.points_by_period, period, pts)


_COUNTER_FIELDS = {
    EventType.ASSIST: "assists",
    EventType.STEAL: "steals",
    EventType.BLOCK: "blocks",
    EventType.TURNOVER: "turnovers",
    EventType.FOUL: "fouls",
}


def _increment_counter(db: Session, event: GameEvent, field: str):
    """Increment a single counter field on both player and team stats."""
    if event.player_id:
        pstats = get_or_create_player_stats(db, event.game_id, event.player_id, event.team_id)
        setattr(pstats, field, getattr(pstats, field) + 1)
    tstats = get_or_create_team_stats(db, event.game_id, event.team_id)
    setattr(tstats, field, getattr(tstats, field) + 1)


def update_stats_for_event(db: Session, event: GameEvent, game: Game):
    """
    Main stats dispatcher — routes each event type to the right stat updates.

    Called once per event on creation, and replayed in order during a rebuild.
    Updates both player-level and team-level stats in a single pass.
    """
    period = event.period.value if isinstance(event.period, enum.Enum) else event.period

    if event.event_type in (EventType.SHOT_MADE, EventType.SHOT_MISSED):
        made = event.event_type == EventType.SHOT_MADE
        pts = _points_for_shot(event.shot_type) if made else 0

        if event.player_id:
            pstats = get_or_create_player_stats(db, event.game_id, event.player_id, event.team_id)
            _apply_shot_stats(pstats, event.shot_type, made, pts, period)

        tstats = get_or_create_team_stats(db, event.game_id, event.team_id)
        _apply_shot_stats(tstats, event.shot_type, made, pts, period)
        # Team-only: track FG attempts/makes by period (excludes free throws)
        if event.shot_type != ShotType.FREE_THROW:
            tstats.fg_attempted_by_period = _increment_json_period(tstats.fg_attempted_by_period, period, 1)
            if made:
                tstats.fg_made_by_period = _increment_json_period(tstats.fg_made_by_period, period, 1)

        # Plus/minus: adjust for all on-court players when points are scored
        if made:
            _update_plus_minus(db, event.game_id, event.team_id, pts, game)

    elif event.event_type == EventType.REBOUND:
        # Classify as offensive or defensive by comparing the rebounder's team
        # to the team that missed the most recent shot.
        prev_miss = (
            db.query(GameEvent)
            .filter(
                GameEvent.game_id == event.game_id,
                GameEvent.event_type == EventType.SHOT_MISSED,
                GameEvent.id < event.id,
            )
            .order_by(GameEvent.id.desc())
            .first()
        )
        is_offensive = prev_miss is not None and prev_miss.team_id == event.team_id

        if event.player_id:
            pstats = get_or_create_player_stats(db, event.game_id, event.player_id, event.team_id)
            if is_offensive:
                pstats.rebounds_offensive += 1
            else:
                pstats.rebounds_defensive += 1
            pstats.rebounds_total += 1

        tstats = get_or_create_team_stats(db, event.game_id, event.team_id)
        if is_offensive:
            tstats.rebounds_offensive += 1
        else:
            tstats.rebounds_defensive += 1
        tstats.rebounds_total += 1

    elif event.event_type in _COUNTER_FIELDS:
        _increment_counter(db, event, _COUNTER_FIELDS[event.event_type])

    elif event.event_type == EventType.TIMEOUT:
        tstats = get_or_create_team_stats(db, event.game_id, event.team_id)
        tstats.timeouts += 1

    elif event.event_type == EventType.SUBSTITUTION:
        # Convention: player_id = exiting player, second_player_id = entering player.
        # On exit, accumulate elapsed seconds since the player last entered.
        if event.player_id:
            exiting = get_or_create_player_stats(db, event.game_id, event.player_id, event.team_id)
            if exiting.is_on_court and exiting.last_sub_clock is not None:
                elapsed = _calc_elapsed_seconds(
                    exiting.last_sub_period, exiting.last_sub_clock,
                    period, event.game_clock_seconds,
                )
                exiting.seconds_played += elapsed
            exiting.is_on_court = False
            exiting.last_sub_clock = event.game_clock_seconds
            exiting.last_sub_period = period

        if event.second_player_id:
            entering = get_or_create_player_stats(db, event.game_id, event.second_player_id, event.team_id)
            entering.is_on_court = True
            entering.last_sub_clock = event.game_clock_seconds
            entering.last_sub_period = period

    db.flush()


def rebuild_game_stats(db: Session, game_id: int):
    """Delete all stats for a game and replay events to rebuild them."""
    db.query(PlayerGameStats).filter(PlayerGameStats.game_id == game_id).delete()
    db.query(TeamGameStats).filter(TeamGameStats.game_id == game_id).delete()
    db.flush()

    game = db.query(Game).filter(Game.id == game_id).first()
    events = (
        db.query(GameEvent)
        .filter(GameEvent.game_id == game_id)
        .order_by(GameEvent.period, GameEvent.game_clock_seconds.desc(), GameEvent.id)
        .all()
    )
    for event in events:
        update_stats_for_event(db, event, game)
    db.commit()
