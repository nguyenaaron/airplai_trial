import enum


# str mixin makes enum values JSON-serializable (e.g. "SHOT_MADE" instead of 1).

class EventType(str, enum.Enum):
    SHOT_MADE = "SHOT_MADE"
    SHOT_MISSED = "SHOT_MISSED"
    FOUL = "FOUL"
    SUBSTITUTION = "SUBSTITUTION"      # player_id exits, second_player_id enters
    TIMEOUT = "TIMEOUT"
    TURNOVER = "TURNOVER"
    REBOUND = "REBOUND"
    STEAL = "STEAL"
    BLOCK = "BLOCK"
    ASSIST = "ASSIST"                  # player_id = passer, second_player_id = scorer
    GAME_START = "GAME_START"
    GAME_END = "GAME_END"


class Period(str, enum.Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    OT1 = "OT1"
    OT2 = "OT2"


class ShotType(str, enum.Enum):
    TWO_POINT = "TWO_POINT"
    THREE_POINT = "THREE_POINT"
    FREE_THROW = "FREE_THROW"
