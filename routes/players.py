from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Player
from schemas import PlayerCreate, PlayerOut

router = APIRouter(prefix="/players", tags=["players"])


@router.post("", response_model=PlayerOut)
def create_player(player: PlayerCreate, db: Session = Depends(get_db)):
    db_player = Player(**player.model_dump())
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    return db_player
