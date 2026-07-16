import logging
import threading
import time


LOG = logging.getLogger(__name__)


class CameraAdapter(object):
    def __init__(self, config, simulation=False, backend="opencv"):
        self.config = config
        self.simulation = simulation
        self.backend = backend
        self.capture = None
        self.pop_camera = None
        self.frame = None
        self.ok = False
        self.running = False
        self._lock = threading.Lock()
        self._thread = None
        self.frame_sequence = 0
        self.frame_timestamp = 0.0

    def start(self):
        import cv2
        if self.simulation:
            self.ok = True
            self.running = True
            return
        if self.backend == "pop":
            from pop import Pilot
            self.pop_camera = Pilot.Camera(
                width=int(self.config["width"]), height=int(self.config["height"]))
            self.running = True
            self._thread = threading.Thread(target=self._reader, name="pop-camera-reader")
            self._thread.daemon = True
            self._thread.start()
            return
        from pop import Util
        pipeline = Util.gstrmer(width=self.config["width"], height=self.config["height"],
                                fps=self.config["fps"], flip=self.config["flip_method"])
        self.capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not self.capture.isOpened():
            raise RuntimeError("CSI camera could not be opened; verify flip_method and nvargus-daemon")
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.running = True
        self._thread = threading.Thread(target=self._reader, name="camera-reader")
        self._thread.daemon = True
        self._thread.start()

    def _reader(self):
        while self.running:
            if self.backend == "pop":
                frame = getattr(self.pop_camera, "value", None)
                ok = frame is not None
                if ok:
                    frame = frame.copy()
            else:
                ok, frame = self.capture.read()
            with self._lock:
                self.ok = bool(ok)
                if ok:
                    self.frame = frame
                    self.frame_sequence += 1
                    self.frame_timestamp = time.time()
            if self.backend == "pop":
                time.sleep(1.0 / max(1.0, float(self.config.get("fps", 30))))
            if not ok:
                time.sleep(0.05)

    def read(self):
        if self.simulation:
            import cv2
            import numpy as np
            frame = np.zeros((self.config["height"], self.config["width"], 3), dtype=np.uint8)
            cv2.putText(frame, "SIMULATION", (24, 52), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (70, 220, 255), 2)
            return True, frame
        with self._lock:
            return self.ok, None if self.frame is None else self.frame.copy()

    def stop(self):
        self.running = False
        if self.capture is not None:
            self.capture.release()
        if self.pop_camera is not None:
            for method_name in ("stop", "close", "release"):
                method = getattr(self.pop_camera, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        LOG.exception("POP camera %s failed", method_name)
                    break


def letterbox(image, width, height, color=(114, 114, 114)):
    """Resize without distortion to an exact 32-multiple canvas."""
    import cv2
    import numpy as np
    if width % 32 or height % 32:
        raise ValueError("letterbox output dimensions must be multiples of 32")
    source_h, source_w = image.shape[:2]
    ratio = min(float(width) / source_w, float(height) / source_h)
    new_w, new_h = int(round(source_w * ratio)), int(round(source_h * ratio))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((height, width, 3), color, dtype=np.uint8)
    left, top = (width - new_w) // 2, (height - new_h) // 2
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas, ratio, (left, top)
