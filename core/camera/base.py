"""CameraInterface: the only way core logic gets frames. Hardware specifics live in adapters."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import numpy as np


class CameraError(RuntimeError):
    pass


class CameraInterface(ABC):
    @abstractmethod
    def open(self) -> None:
        """Open the device. Raises CameraError if it cannot be opened."""

    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        """Return one BGR frame, or None if no frame could be read."""

    @abstractmethod
    def close(self) -> None:
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...

    def describe(self) -> Dict[str, Any]:
        return {"type": type(self).__name__}
