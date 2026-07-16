import glob
import logging
import statistics
import threading
import time


LOG = logging.getLogger(__name__)


def angular_distance(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


class LidarAdapter(object):
    def __init__(self, config, simulation=False):
        self.config = config
        self.simulation = simulation
        self.points = {}
        self.ok = simulation or not config.get("enabled", True)
        self.running = False
        self.device = None
        self._lock = threading.Lock()
        self._thread = None

    def _ports(self):
        if self.config.get("port") != "auto":
            return [self.config["port"]]
        return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))

    def start(self):
        if self.simulation or not self.config.get("enabled", True):
            self.ok = True
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, name="lidar-reader")
        self._thread.daemon = True
        self._thread.start()

    def _run(self):
        from rplidar import RPLidar
        while self.running:
            for port in self._ports():
                for baud in self.config.get("baudrates", [115200, 256000]):
                    lidar = None
                    try:
                        LOG.info("Trying RPLidar on %s at %s", port, baud)
                        lidar = RPLidar(port, baudrate=int(baud), timeout=1)
                        self.device = "%s@%s" % (port, baud)
                        for scan in lidar.iter_scans(max_buf_meas=800):
                            if not self.running:
                                break
                            points = {}
                            for quality, angle, distance_mm in scan:
                                if quality > 0 and distance_mm > 0:
                                    angle = (-angle if self.config.get("clockwise") else angle)
                                    angle = (angle + self.config.get("front_angle_deg", 0.0)) % 360.0
                                    points[round(angle, 1)] = distance_mm / 1000.0
                            with self._lock:
                                self.points = points
                                self.ok = bool(points)
                        break
                    except Exception as exc:
                        LOG.warning("RPLidar probe %s@%s failed: %s", port, baud, exc)
                        self.ok = False
                    finally:
                        if lidar is not None:
                            try:
                                lidar.stop()
                                lidar.disconnect()
                            except Exception:
                                pass
                if self.ok:
                    break
            if not self.ok:
                time.sleep(2.0)

    def snapshot(self):
        with self._lock:
            return dict(self.points)

    def distance_at(self, angle, window_deg=None):
        window = float(window_deg or self.config.get("association_window_deg", 5.0))
        values = [distance for point_angle, distance in self.snapshot().items()
                  if angular_distance(point_angle, angle) <= window]
        return statistics.median(values) if values else None

    def front_obstacle_distance(self, half_angle=20.0):
        values = [distance for angle, distance in self.snapshot().items()
                  if angular_distance(angle, 0.0) <= half_angle]
        return min(values) if values else None

    def camera_x_distance(self, center_x, image_width, camera_yaw_deg=0.0):
        relative = (float(center_x) - image_width / 2.0) / (image_width / 2.0)
        camera_angle = (relative * (self.config.get("camera_fov_deg", 160.0) / 2.0) +
                        float(camera_yaw_deg))
        return self.distance_at(camera_angle)

    def stop(self):
        self.running = False
