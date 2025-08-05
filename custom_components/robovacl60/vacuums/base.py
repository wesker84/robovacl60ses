from enum import IntEnum, StrEnum
from typing import Protocol, Dict, List, Any, Type, Optional


class RoboVacEntityFeature(IntEnum):
    """Supported features of the RoboVac entity."""
    EDGE = 1
    SMALL_ROOM = 2
    CLEANING_TIME = 4
    CLEANING_AREA = 8
    DO_NOT_DISTURB = 16
    AUTO_RETURN = 32
    CONSUMABLES = 64
    ROOM = 128
    ZONE = 256
    MAP = 512
    BOOST_IQ = 1024


class RobovacCommand(StrEnum):
    START_PAUSE = "start_pause"
    DIRECTION = "direction"
    MODE = "mode"
    STATUS = "status"
    RETURN_HOME = "return_home"
    FAN_SPEED = "fan_speed"
    LOCATE = "locate"
    BATTERY = "battery"
    ERROR = "error"
    CLEANING_AREA = "cleaning_area"
    CLEANING_TIME = "cleaning_time"
    AUTO_RETURN = "auto_return"
    DO_NOT_DISTURB = "do_not_disturb"
    BOOST_IQ = "boost_iq"
    CONSUMABLES = "consumables"


class TuyaCodes(StrEnum):
    """DPS codes mapped for T2267 (L60) vacuum.

    These are confirmed to work with base64 encoding and Tuya API.
    """
    START_PAUSE = "156"
    DIRECTION = "155"
    MODE = "152"
    STATUS = "153"
    RETURN_HOME = "173"
    FAN_SPEED = "158"
    LOCATE = "160"
    BATTERY_LEVEL = "163"
    ERROR_CODE = "177"
    DO_NOT_DISTURB = "157"
    BOOST_IQ = "159"
    CONSUMABLES = "168"


TUYA_CONSUMABLES_CODES: List[str] = ["168"]  # Updated for T2267 compatibility


class RobovacModelDetails(Protocol):
    homeassistant_features: int
    robovac_features: int
    commands: Dict[RobovacCommand, Dict[str, Any]]
    dps_codes: Dict[str, str]
4