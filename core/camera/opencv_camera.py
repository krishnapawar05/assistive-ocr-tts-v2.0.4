"""OpenCV camera adapter: USB/UVC index, or a GStreamer pipeline (Jetson CSI via nvarguscamerasrc)."""
import logging
import sys
import threading
from typing import Any, Dict, Optional, Union

import cv2
import numpy as np

from .base import CameraError, CameraInterface

logger = logging.getLogger("camera")


class OpenCVCamera(CameraInterface):
    _hw_lock = threading.Lock()

    def __init__(self, cam_cfg: Dict[str, Any]):
        self.cfg = cam_cfg
        self._cap: Optional[cv2.VideoCapture] = None

    def resolution(self):
        w, h = self.cfg["resolutions"][self.cfg["resolution"]]
        return int(w), int(h)

    def source(self) -> Union[int, str]:
        if self.cfg["source_type"] == "gstreamer":
            w, h = self.resolution()
            return ("nvarguscamerasrc ! video/x-raw(memory:NVMM), "
                    f"width={w}, height={h}, framerate={int(self.cfg['gstreamer_framerate'])}/1 ! "
                    "nvvidconv ! videoconvert ! appsink")
        return int(self.cfg["camera_id"])

    def open(self) -> None:
        self.close()
        src = self.source()
        with self._hw_lock:
            cap = None
            try:
                if isinstance(src, str):
                    cap = cv2.VideoCapture(src, cv2.CAP_GSTREAMER)
                elif sys.platform == "win32":
                    # DirectShow prevents MSMF audio/video COM lockups and index collisions
                    cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap = cv2.VideoCapture(src)
                else:
                    cap = cv2.VideoCapture(src)

                if not cap.isOpened():
                    try:
                        cap.release()
                    except Exception:
                        pass
                    raise CameraError(f"cannot open camera source {src!r}")

                if isinstance(src, int):
                    w, h = self.resolution()
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                    except (cv2.error, Exception) as e:
                        logger.debug("could not set camera width: %s", e)
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                    except (cv2.error, Exception) as e:
                        logger.debug("could not set camera height: %s", e)
                    try:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, int(self.cfg["buffer_size"]))
                    except (cv2.error, Exception) as e:
                        logger.debug("could not set camera buffer size: %s", e)

                self._cap = cap
            except CameraError:
                raise
            except (cv2.error, Exception) as e:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                raise CameraError(f"cannot open camera source {src!r}: {e}") from e

    def read(self) -> Optional[np.ndarray]:
        if self._cap is None:
            return None
        try:
            ok, frame = self._cap.read()
        except (cv2.error, Exception) as e:
            logger.debug("camera read error: %s", e)
            return None
        return frame if ok and frame is not None and frame.size else None

    def close(self) -> None:
        with self._hw_lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except (cv2.error, Exception) as e:
                    logger.debug("camera release error: %s", e)
                finally:
                    self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def describe(self) -> Dict[str, Any]:
        src = self.source()
        return {"type": "opencv", "source": src if isinstance(src, int) else "gstreamer",
                "resolution": self.cfg["resolution"]}


def create_camera(cam_cfg: Dict[str, Any]) -> CameraInterface:
    return OpenCVCamera(cam_cfg)
