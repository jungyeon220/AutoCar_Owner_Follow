import time


class Detection(object):
    def __init__(self, box, confidence, track_id=None, feature=None, keypoints=None):
        self.box = tuple(int(v) for v in box)
        self.confidence = float(confidence)
        self.track_id = track_id
        self.feature = feature
        self.keypoints = keypoints or {}

    @property
    def center(self):
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def area(self):
        x1, y1, x2, y2 = self.box
        return max(0, x2 - x1) * max(0, y2 - y1)


class Telemetry(object):
    def __init__(self):
        self.state = "INIT"
        self.reason = "starting"
        self.owner_status = "none"
        self.bluetooth_connected = False
        self.camera_ok = False
        self.lidar_ok = False
        self.owner_distance_m = None
        self.owner_height_ratio = None
        self.target_owner_height_ratio = 0.0
        self.obstacle_distance_m = None
        self.speed = 0
        self.steering = 0.0
        self.speed_limit = 0
        self.speed_limit_min = 0
        self.speed_limit_cap = 0
        self.target_distance_m = 0.0
        self.stop_distance_m = 0.0
        self.emergency_distance_m = 0.0
        self.camera_pan = 90.0
        self.camera_tilt = 45.0
        self.camera_tilt_min = 0.0
        self.camera_tilt_max = 90.0
        self.cds_ok = False
        self.cds_value = None
        self.fps = 0.0
        self.camera_fps = 0.0
        self.inference_target_fps = 0.0
        self.people = 0
        self.memory_rss_mb = 0.0
        self.memory_collections = 0
        self.inference_latency_ms = 0.0
        self.pose_latency_ms = 0.0
        self.processing_latency_ms = 0.0
        self.jpeg_encode_latency_ms = 0.0
        self.video_frame_age_ms = 0.0
        self.pose_ok = False
        self.pose_error = ""
        self.gesture_status = "idle"
        self.aruco_ok = False
        self.aruco_status = "idle"
        self.aruco_id = None
        self.aruco_side_px = 0.0
        self.aruco_latency_ms = 0.0
        self.selection_status = "idle"
        self.selection_hits = 0
        self.selection_locked = False
        self.registration_progress = 0.0
        self.updated_at = time.time()

    def as_dict(self):
        return dict(self.__dict__)
