from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from enums import EventType, Period
from models import Game, GameEvent, PlayerGameStats, TeamGameStats
from schemas import (
    PlayerGameStatsOut, TeamGameStatsOut, PlayerSeasonStatsOut, TeamSeasonStatsOut,
    ShotChartEntryOut, ShotChartOut,
)
from stats import rebuild_game_stats

router = APIRouter(tags=["stats"])


@router.get("/games/{game_id}/stats/players")
def get_player_game_stats(game_id: int, db: Session = Depends(get_db)):
    """All player box scores for a game — one entry per player who has events."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    stats = db.query(PlayerGameStats).filter(PlayerGameStats.game_id == game_id).all()
    return [PlayerGameStatsOut.from_orm_with_json(s) for s in stats]


@router.get("/games/{game_id}/stats/teams")
def get_team_game_stats(game_id: int, db: Session = Depends(get_db)):
    """Both team box scores for a game (home and away)."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    stats = db.query(TeamGameStats).filter(TeamGameStats.game_id == game_id).all()
    return [TeamGameStatsOut.from_orm_with_json(s) for s in stats]


@router.get("/players/{player_id}/stats")
def get_player_stats(
    player_id: int,
    game_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Player stats across all games, with optional game_id filter for a single game."""
    query = db.query(PlayerGameStats).filter(PlayerGameStats.player_id == player_id)
    if game_id is not None:
        query = query.filter(PlayerGameStats.game_id == game_id)
    stats = query.all()
    return [PlayerGameStatsOut.from_orm_with_json(s) for s in stats]


@router.get("/players/{player_id}/season-stats", response_model=PlayerSeasonStatsOut)
def get_player_season_stats(player_id: int, db: Session = Depends(get_db)):
    """Aggregated stats for a player across all games."""
    rows = db.query(PlayerGameStats).filter(PlayerGameStats.player_id == player_id).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No stats found for player")

    gp = len(rows)
    pts = sum(r.points for r in rows)
    reb = sum(r.rebounds_total for r in rows)
    ast = sum(r.assists for r in rows)
    tpm = sum(r.three_point_made for r in rows)
    stl = sum(r.steals for r in rows)
    blk = sum(r.blocks for r in rows)
    tov = sum(r.turnovers for r in rows)
    fgm = sum(r.field_goals_made for r in rows)
    fga = sum(r.field_goals_attempted for r in rows)
    tpa = sum(r.three_point_attempted for r in rows)
    ftm = sum(r.free_throws_made for r in rows)
    fta = sum(r.free_throws_attempted for r in rows)

    fg_pct = round(fgm / fga * 100, 1) if fga > 0 else None
    three_pt_pct = round(tpm / tpa * 100, 1) if tpa > 0 else None
    ft_pct = round(ftm / fta * 100, 1) if fta > 0 else None
    ts_denom = 2 * (fga + 0.44 * fta)
    ts_pct = round(pts / ts_denom * 100, 1) if ts_denom > 0 else None
    efg_pct = round((fgm + 0.5 * tpm) / fga * 100, 1) if fga > 0 else None

    # PLAi Score: raw per-game contribution, then scale 0-100
    raw = (pts + 1.2 * reb + 1.5 * ast + 2 * stl + 2 * blk - tov
           - 0.5 * (fga - fgm) - 0.5 * (fta - ftm)) / gp

    # Scale relative to team output: get all players on same team across same games
    team_id = rows[0].team_id
    game_ids = [r.game_id for r in rows]
    team_rows = db.query(PlayerGameStats).filter(
        PlayerGameStats.game_id.in_(game_ids),
        PlayerGameStats.team_id == team_id,
    ).all()

    team_raw = 0.0
    if team_rows:
        t_pts = sum(r.points for r in team_rows)
        t_reb = sum(r.rebounds_total for r in team_rows)
        t_ast = sum(r.assists for r in team_rows)
        t_stl = sum(r.steals for r in team_rows)
        t_blk = sum(r.blocks for r in team_rows)
        t_tov = sum(r.turnovers for r in team_rows)
        t_fgm = sum(r.field_goals_made for r in team_rows)
        t_fga = sum(r.field_goals_attempted for r in team_rows)
        t_ftm = sum(r.free_throws_made for r in team_rows)
        t_fta = sum(r.free_throws_attempted for r in team_rows)
        team_raw = (t_pts + 1.2 * t_reb + 1.5 * t_ast + 2 * t_stl + 2 * t_blk - t_tov
                    - 0.5 * (t_fga - t_fgm) - 0.5 * (t_fta - t_ftm)) / gp

    plai_score = round(raw / team_raw * 100, 1) if team_raw > 0 else None

    return PlayerSeasonStatsOut(
        player_id=player_id,
        team_id=team_id,
        games_played=gp,
        points=pts,
        rebounds=reb,
        assists=ast,
        three_point_made=tpm,
        steals=stl,
        blocks=blk,
        turnovers=tov,
        fg_pct=fg_pct,
        three_pt_pct=three_pt_pct,
        ft_pct=ft_pct,
        ts_pct=ts_pct,
        efg_pct=efg_pct,
        plai_score=plai_score,
    )


@router.get("/teams/{team_id}/season-stats", response_model=TeamSeasonStatsOut)
def get_team_season_stats(team_id: str, db: Session = Depends(get_db)):
    """Aggregated stats for a team across all games."""
    rows = db.query(TeamGameStats).filter(TeamGameStats.team_id == team_id).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No stats found for team")

    gp = len(rows)
    pts = sum(r.points for r in rows)
    reb = sum(r.rebounds_total for r in rows)
    ast = sum(r.assists for r in rows)
    stl = sum(r.steals for r in rows)
    blk = sum(r.blocks for r in rows)
    tov = sum(r.turnovers for r in rows)
    fgm = sum(r.field_goals_made for r in rows)
    fga = sum(r.field_goals_attempted for r in rows)
    tpm = sum(r.three_point_made for r in rows)
    tpa = sum(r.three_point_attempted for r in rows)
    ftm = sum(r.free_throws_made for r in rows)
    fta = sum(r.free_throws_attempted for r in rows)
    oreb = sum(r.rebounds_offensive for r in rows)

    fg_pct = round(fgm / fga * 100, 1) if fga > 0 else None
    three_pt_pct = round(tpm / tpa * 100, 1) if tpa > 0 else None
    ts_denom = 2 * (fga + 0.44 * fta)
    ts_pct = round(pts / ts_denom * 100, 1) if ts_denom > 0 else None
    efg_pct = round((fgm + 0.5 * tpm) / fga * 100, 1) if fga > 0 else None

    # Possessions ≈ FGA - OREB + TOV + 0.44 * FTA
    poss = fga - oreb + tov + 0.44 * fta
    ortg = round(pts / poss * 100, 1) if poss > 0 else None
    pace = round(poss / gp, 1) if gp > 0 else None

    # W/L and DRtg: compare against opponent per game
    wins = 0
    losses = 0
    opp_pts_total = 0
    for r in rows:
        opp = db.query(TeamGameStats).filter(
            TeamGameStats.game_id == r.game_id,
            TeamGameStats.team_id != team_id,
        ).first()
        if opp:
            opp_pts_total += opp.points
            if r.points > opp.points:
                wins += 1
            elif r.points < opp.points:
                losses += 1
            # ties count as neither

    drtg = round(opp_pts_total / poss * 100, 1) if poss > 0 else None

    return TeamSeasonStatsOut(
        team_id=team_id,
        games_played=gp,
        wins=wins,
        losses=losses,
        points=pts,
        rebounds=reb,
        assists=ast,
        steals=stl,
        blocks=blk,
        turnovers=tov,
        fg_pct=fg_pct,
        three_pt_pct=three_pt_pct,
        ts_pct=ts_pct,
        efg_pct=efg_pct,
        ortg=ortg,
        drtg=drtg,
        pace=pace,
    )


@router.get("/games/{game_id}/shot-chart", response_model=ShotChartOut)
def get_shot_chart(
    game_id: int,
    player_id: Optional[int] = None,
    team_id: Optional[str] = None,
    period: Optional[Period] = None,
    db: Session = Depends(get_db),
):
    """Shot chart data: locations of all shots with coordinates for a game."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    query = db.query(GameEvent).filter(
        GameEvent.game_id == game_id,
        GameEvent.event_type.in_([EventType.SHOT_MADE, EventType.SHOT_MISSED]),
        GameEvent.court_x.isnot(None),
        GameEvent.court_y.isnot(None),
    )
    if player_id is not None:
        query = query.filter(GameEvent.player_id == player_id)
    if team_id is not None:
        query = query.filter(GameEvent.team_id == team_id)
    if period is not None:
        query = query.filter(GameEvent.period == period)

    events = query.all()

    shots = [
        ShotChartEntryOut(
            event_id=e.id,
            player_id=e.player_id,
            team_id=e.team_id,
            period=e.period,
            game_clock_seconds=e.game_clock_seconds,
            shot_type=e.shot_type,
            event_type=e.event_type,
            court_x=e.court_x,
            court_y=e.court_y,
        )
        for e in events
    ]

    total_made = sum(1 for e in events if e.event_type == EventType.SHOT_MADE)
    total_attempted = len(events)
    fg_pct = round(total_made / total_attempted * 100, 1) if total_attempted > 0 else None

    return ShotChartOut(
        shots=shots,
        total_made=total_made,
        total_attempted=total_attempted,
        fg_pct=fg_pct,
    )


@router.post("/games/{game_id}/stats/rebuild")
def rebuild_stats(game_id: int, db: Session = Depends(get_db)):
    """Wipe and recalculate all stats from events. Useful after manual corrections."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    rebuild_game_stats(db, game_id)
    return {"status": "ok", "game_id": game_id}
