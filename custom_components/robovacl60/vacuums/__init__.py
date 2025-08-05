from typing import Dict, Type
from .T2267 import T2267
from .base import RobovacModelDetails


ROBOVAC_MODELS: Dict[str, Type[RobovacModelDetails]] = {
    "T2267": T2267,
}

