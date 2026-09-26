"""Engine lifecycle status shared by OCR and TTS adapters."""
from enum import Enum


class EngineStatus(str, Enum):
    """Lifecycle state of an engine. Only READY engines are used."""

    UNINITIALIZED = "UNINITIALIZED"
    READY = "READY"
    DISABLED = "DISABLED"                          # turned off in config
    NOT_AVAILABLE = "NOT_AVAILABLE"                # package or external runtime missing
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"    # runtime present, local model files missing
    LANGUAGE_NOT_SUPPORTED = "LANGUAGE_NOT_SUPPORTED"
    INIT_FAILED = "INIT_FAILED"                    # present but failed to load (a defect, not "unavailable")


#: Statuses that legitimately mean "this machine lacks something". INIT_FAILED is excluded:
#: an installed engine that crashes on load is a failure, never reported as NOT_AVAILABLE.
UNAVAILABLE_STATUSES = frozenset({
    EngineStatus.DISABLED,
    EngineStatus.NOT_AVAILABLE,
    EngineStatus.MODEL_NOT_AVAILABLE,
    EngineStatus.LANGUAGE_NOT_SUPPORTED,
})
