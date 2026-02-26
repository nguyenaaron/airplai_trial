from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from enums import EventType, Period
from models import Game, GameEvent
from schemas import EventCreate, EventOut, EventUpdate
from stats import update_stats_for_event, rebuild_game_stats

router = APIRouter(tags=["events"])


@router.post("/games/{game_id}/events", response_model=EventOut)
def create_event(game_id: int, event: EventCreate, db: Session = Depends(get_db)):
    """Tag a new event in a game. Automatically updates player and team stats."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if event.team_id not in (game.home_team_id, game.away_team_id):
        raise HTTPException(
            status_code=422,
            detail=f"team_id '{event.team_id}' is not a participant in this game"
        )
    db_event = GameEvent(game_id=game_id, **event.model_dump())
    db.add(db_event)
    db.flush()  # flush to assign an ID before stats update (needed for rebound lookups)
    update_stats_for_event(db, db_event, game)
    db.commit()
    db.refresh(db_event)
    return db_event


@router.delete("/games/{game_id}/events/{event_id}")
def delete_event(game_id: int, event_id: int, db: Session = Depends(get_db)):
    """Delete an event and recalculate stats."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    event = db.query(GameEvent).filter(
        GameEvent.id == event_id, GameEvent.game_id == game_id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.flush()
    rebuild_game_stats(db, game_id)
    return {"status": "deleted", "event_id": event_id}


@router.patch("/games/{game_id}/events/{event_id}", response_model=EventOut)
def patch_event(game_id: int, event_id: int, update: EventUpdate, db: Session = Depends(get_db)):
    """Update specific fields of an event and recalculate stats."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    event = db.query(GameEvent).filter(
        GameEvent.id == event_id, GameEvent.game_id == game_id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    update_data = update.model_dump(exclude_unset=True)
    if "team_id" in update_data and update_data["team_id"] not in (game.home_team_id, game.away_team_id):
        raise HTTPException(
            status_code=422,
            detail=f"team_id '{update_data['team_id']}' is not a participant in this game"
        )
    for field, value in update_data.items():
        setattr(event, field, value)
    db.flush()
    rebuild_game_stats(db, game_id)
    db.refresh(event)
    return event


@router.get("/games/{game_id}/events", response_model=List[EventOut])
def get_events(
    game_id: int,
    event_type: Optional[EventType] = None,
    period: Optional[Period] = None,
    player_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Query events for a game with optional filters by type, period, or player."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    query = db.query(GameEvent).filter(GameEvent.game_id == game_id)
    if event_type:
        query = query.filter(GameEvent.event_type == event_type)
    if period:
        query = query.filter(GameEvent.period == period)
    if player_id:
        # Match either primary or secondary player (e.g. find all events involving a player)
        query = query.filter(
            (GameEvent.player_id == player_id)
            | (GameEvent.second_player_id == player_id)
        )
    # Ordered chronologically: by period, then descending clock (higher clock = earlier in period)
    return query.order_by(GameEvent.period, GameEvent.game_clock_seconds.desc()).all()


@router.get("/games/{game_id}/timeline", response_model=List[EventOut])
def get_timeline(game_id: int, db: Session = Depends(get_db)):
    """Full chronological game story — all events ordered by period and clock."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return (
        db.query(GameEvent)
        .filter(GameEvent.game_id == game_id)
        .order_by(GameEvent.period, GameEvent.game_clock_seconds.desc())
        .all()
    )


@router.get("/games/{game_id}/highlights", response_model=List[EventOut])
def get_highlights(
    game_id: int,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """Clip-ready events: only those linked to camera footage above a confidence threshold."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return (
        db.query(GameEvent)
        .filter(
            GameEvent.game_id == game_id,
            GameEvent.camera_id.isnot(None),
            GameEvent.video_timestamp_seconds.isnot(None),
            GameEvent.confidence >= min_confidence,
        )
        .order_by(GameEvent.period, GameEvent.game_clock_seconds.desc())
        .all()
    )


@router.get("/players/{player_id}/highlights", response_model=List[EventOut])
def get_player_highlights(
    player_id: int,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """All highlight clips for a player across all games (parent-facing endpoint)."""
    return (
        db.query(GameEvent)
        .filter(
            (GameEvent.player_id == player_id)
            | (GameEvent.second_player_id == player_id),
            GameEvent.camera_id.isnot(None),
            GameEvent.video_timestamp_seconds.isnot(None),
            GameEvent.confidence >= min_confidence,
        )
        .order_by(GameEvent.game_id, GameEvent.period, GameEvent.game_clock_seconds.desc())
        .all()
    )
