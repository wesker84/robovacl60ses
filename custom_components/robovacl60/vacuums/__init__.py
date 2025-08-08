from typing import Dict, Type
from .T2277 import T2277
from .base import RobovacModelDetails


ROBOVAC_MODELS: Dict[str, Type[RobovacModelDetails]] = {
    "T2277": T2277,
}

