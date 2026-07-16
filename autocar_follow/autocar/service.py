import gc
from collections import deque
import json
import logging
import os
import threading
import time

from autocar.adapters.bluetooth import BluetoothMonitor
from autocar.adapters.camera import CameraAdapter
from autocar.adapters.cds import CdsAdapter
from autocar.adapters.lidar import LidarAdapter
from autocar.adapters.tts import TTSAdapter
from autocar.adapters.vehicle import VehicleAdapter
from autocar.adapters.vision import PersonDetector, nearest_visual_person
from autocar.controller import CameraTrackingController, DrivingController
from autocar.models import Telemetry
from autocar.owner import AppearanceEncoder, OwnerProfile, classify_candidates
from autocar.state_machine import StateMachine
LOG = logging.getLogger(__name__)
ACTIVE_STATES = ("SELECT_NEAREST_OWNER", "REGISTER_OWNER", "FOLLOW_OWNER",
                 "SEARCH_OWNER", "BLOCKED", "REAUTHENTICATION", "MANUAL")


class AutoCarService(object):
    def __init__(self, config):
        self.config = config
        simulation = config["runtime"].get("simulation", False)
        self.state = StateMachine()
        self.telemetry = Telemetry()
        detector_backend = str(config["detector"].get("backend", "pop")).lower()
        camera_backend = "pop" if detector_backend == "pop" else "opencv"
        self.camera = CameraAdapter(config["camera"], simulation, camera_backend)
        self.cds = CdsAdapter(config.get("cds", {}), simulation)
        self.vehicle = VehicleAdapter(simulation)
        self.lidar = LidarAdapter(config["lidar"], simulation)
        self.bluetooth = BluetoothMonitor(config["bluetooth"], simulation)
        self.tts = TTSAdapter(config["tts"], simulation)
        self.detector = PersonDetector(
            config["detector"], config["camera"], simulation,
            camera_adapter=self.camera)
        self.encoder = AppearanceEncoder()
        self.profile = OwnerProfile()
        self.controller = DrivingController(config["driving"])
        self.camera_controller = CameraTrackingController(config.get("camera_tracking", {}))
        self.running = False
        self.thread = None
        self.frame = None
        self.annotated_frame = None
        self._annotated_monotonic = 0.0
        self.detections = []
        self._frame_lock = threading.Lock()
        self._data_lock = threading.RLock()
        self._search_started = None
        self._lost_announced = False
        self._manual_deadline = 0.0
        self._center_candidate_track_id = None
        self._center_candidate_since = None
        self._selection_hits = deque(maxlen=int(
            config["selection"].get("sample_count", 5)))
        self._selection_candidate_track_id = None
        self._selection_locked = False
        self._selection_missing_since = None
        self._memory_cleanup_seconds = float(
            config["runtime"].get("memory_cleanup_seconds", 300.0))
        self._last_memory_cleanup = time.time()
        self.telemetry.memory_rss_mb = self._rss_mb()

    def start(self):
        self.vehicle.start()
        camera_position = self.camera_controller.reset()
        if camera_position is not None and self.camera_controller.enabled:
            self.vehicle.pan_tilt(camera_position[0], camera_position[1])
        self.camera.start()
        self.cds.start()
        self.lidar.start()
        self.bluetooth.start()
        self.detector.start()
        self.state.transition("IDLE", "dashboard ready")
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="autocar-control")
        self.thread.daemon = True
        self.thread.start()

    def shutdown(self):
        self.running = False
        self.vehicle.stop()
        self.camera.stop()
        self.cds.stop()
        self.lidar.stop()
        self.bluetooth.stop()

    def request_follow(self):
        with self._data_lock:
            if self.state.state != "IDLE":
                raise ValueError("follow cannot start from %s" % self.state.state)
            if not self.bluetooth.connected:
                raise ValueError("registered Bluetooth device is not connected")
            if not self.telemetry.camera_ok:
                raise ValueError("camera is not ready")
            if self.config["lidar"].get("enabled", True) and not self.lidar.ok:
                raise ValueError("LiDAR is not ready")
            self.state.transition("SELECT_NEAREST_OWNER", "selecting nearest visible person")
            self.telemetry.selection_status = "selecting-nearest"
            self.profile = OwnerProfile()
            self.controller.reset_tracking()
            self._reset_center_candidate()
            camera_position = self.camera_controller.reset()
            if camera_position is not None and self.camera_controller.enabled:
                self.vehicle.pan_tilt(camera_position[0], camera_position[1])

    def stop_follow(self, reason="operator stop"):
        with self._data_lock:
            self.vehicle.stop()
            if self.state.state == "EMERGENCY":
                return
            self.state.transition("IDLE", reason)

    def emergency_stop(self, reason="dashboard emergency stop"):
        with self._data_lock:
            self.vehicle.stop()
            self.state.force_emergency(reason)

    def reset_emergency(self):
        with self._data_lock:
            if self.state.state != "EMERGENCY":
                raise ValueError("system is not in emergency state")
            self.vehicle.stop()
            self.state.transition("IDLE", "emergency reset by authenticated operator")

    def manual(self, command):
        with self._data_lock:
            if self.state.state == "EMERGENCY":
                raise ValueError("reset emergency before manual control")
            if self.state.state != "MANUAL":
                if self.state.state != "IDLE":
                    self.stop_follow("manual takeover")
                self.state.transition("MANUAL", "authenticated manual control")
            speed = int(self.config["driving"].get("manual_max_speed", 25))
            commands = {
                "forward": (speed, 0.0), "backward": (-speed, 0.0),
                "left": (0, -1.0), "right": (0, 1.0), "stop": (0, 0.0)
            }
            if command == "exit":
                self.vehicle.stop()
                self.state.transition("IDLE", "manual control ended")
                return
            if command not in commands:
                raise ValueError("unknown manual command")
            drive = commands[command]
            self.vehicle.drive(drive[0], drive[1])
            self._manual_deadline = time.time() + 0.35

    def set_speed_limit(self, value):
        with self._data_lock:
            if isinstance(value, bool):
                raise ValueError("speed must be an integer")
            try:
                speed = int(value)
            except (TypeError, ValueError):
                raise ValueError("speed must be an integer")
            cap = int(self.config["driving"].get("dashboard_max_speed", 30))
            minimum = int(self.config["driving"].get("min_follow_speed", 50))
            if speed < minimum or speed > cap:
                raise ValueError("speed must be between %s and %s" % (minimum, cap))
            self.config["driving"]["max_speed"] = speed
            self.config["driving"]["manual_max_speed"] = speed
            LOG.info("authenticated operator set runtime speed limit to %s", speed)

    def set_camera_tilt(self, value):
        with self._data_lock:
            if isinstance(value, bool):
                raise ValueError("camera tilt must be a number")
            try:
                tilt = float(value)
            except (TypeError, ValueError):
                raise ValueError("camera tilt must be a number")
            minimum = float(self.config["camera_tracking"].get("tilt_min", 0.0))
            maximum = float(self.config["camera_tracking"].get("tilt_max", 90.0))
            if tilt != tilt or tilt < minimum or tilt > maximum:
                raise ValueError("camera tilt must be between %s and %s" %
                                 (minimum, maximum))
            self.config["camera_tracking"]["tilt_center"] = tilt
            self.camera_controller.tilt = tilt
            self.vehicle.pan_tilt(self.vehicle.pan, tilt)
            LOG.info("authenticated operator set runtime camera tilt to %.1f", tilt)

    def status(self):
        with self._data_lock:
            self.telemetry.state = self.state.state
            self.telemetry.reason = self.state.reason
            self.telemetry.bluetooth_connected = self.bluetooth.connected
            self.telemetry.speed = self.vehicle.speed
            self.telemetry.steering = self.vehicle.steering
            self.telemetry.speed_limit = int(self.config["driving"].get("max_speed", 0))
            self.telemetry.speed_limit_min = int(
                self.config["driving"].get("min_follow_speed", 50))
            self.telemetry.speed_limit_cap = int(
                self.config["driving"].get("dashboard_max_speed", 30))
            self.telemetry.target_distance_m = float(
                self.config["driving"].get("target_distance_m", 0.0))
            self.telemetry.target_owner_height_ratio = float(
                self.config["driving"].get("target_owner_height_ratio", 0.0))
            self.telemetry.stop_distance_m = float(
                self.config["driving"].get("stop_distance_m", 0.0))
            self.telemetry.emergency_distance_m = float(
                self.config["driving"].get("emergency_distance_m", 0.0))
            self.telemetry.camera_pan = self.vehicle.pan
            self.telemetry.camera_tilt = self.vehicle.tilt
            self.telemetry.camera_tilt_min = float(
                self.config["camera_tracking"].get("tilt_min", 0.0))
            self.telemetry.camera_tilt_max = float(
                self.config["camera_tracking"].get("tilt_max", 90.0))
            self.telemetry.cds_ok = self.cds.ok
            self.telemetry.cds_value = self.cds.value
            self.telemetry.camera_fps = float(self.config["camera"].get("fps", 0.0))
            self.telemetry.inference_target_fps = float(
                self.config["runtime"].get("loop_hz", 0.0))
            self.telemetry.aruco_ok = False
            self.telemetry.aruco_status = "disabled"
            self.telemetry.pose_ok = False
            self.telemetry.pose_error = "disabled; nearest-person clothing registration active"
            needed = max(1, int(self.config["owner"].get("registration_frames", 20)))
            if self.state.state in ("FOLLOW_OWNER", "SEARCH_OWNER", "BLOCKED"):
                self.telemetry.registration_progress = 1.0
            else:
                self.telemetry.registration_progress = min(
                    1.0, float(len(self.profile.samples)) / needed)
            with self._frame_lock:
                annotated_at = self._annotated_monotonic
            self.telemetry.video_frame_age_ms = (
                max(0.0, (time.monotonic() - annotated_at) * 1000.0)
                if annotated_at else 0.0)
            self.telemetry.updated_at = time.time()
            return self.telemetry.as_dict()

    def lidar_points(self):
        return [{"angle": angle, "distance": distance}
                for angle, distance in self.lidar.snapshot().items()]

    def jpeg(self):
        import cv2
        encode_started = time.monotonic()
        with self._frame_lock:
            frame = None if self.annotated_frame is None else self.annotated_frame.copy()
        if frame is None:
            return None
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        self._record_latency("jpeg_encode_latency_ms",
                             (time.monotonic() - encode_started) * 1000.0)
        return encoded.tobytes() if ok else None

    def _loop(self):
        interval = 1.0 / float(self.config["runtime"].get("loop_hz", 15))
        last = time.time()
        while self.running:
            started = time.time()
            processing_started = time.monotonic()
            try:
                self._step(started)
            except Exception:
                LOG.exception("control loop failure")
                self.emergency_stop("control loop failure")
            self._record_latency("processing_latency_ms",
                                 (time.monotonic() - processing_started) * 1000.0)
            if started - self._last_memory_cleanup >= self._memory_cleanup_seconds:
                self._cleanup_memory(started)
            elapsed = time.time() - started
            self.telemetry.fps = 1.0 / max(time.time() - last, 1e-3)
            last = time.time()
            time.sleep(max(0.0, interval - elapsed))

    def _step(self, now):
        ok, frame = self.camera.read()
        cds_value = self.cds.read()
        self.telemetry.cds_ok = self.cds.ok
        self.telemetry.cds_value = cds_value
        self.telemetry.camera_ok = ok
        self.telemetry.lidar_ok = self.lidar.ok
        if not ok or frame is None:
            if self.state.state in ACTIVE_STATES:
                self.emergency_stop("camera unavailable")
            return
        if (self.state.state in ACTIVE_STATES and
                self.config["lidar"].get("enabled", True) and not self.lidar.ok):
            self.emergency_stop("LiDAR unavailable")
        inference_started = time.monotonic()
        detections = self.detector.detect(frame)
        self._record_latency("inference_latency_ms",
                             (time.monotonic() - inference_started) * 1000.0)
        for detection in detections:
            detection.feature = self.encoder.encode(frame, detection.box)
        self.detections = detections
        self.telemetry.people = len(detections)
        obstacle = self.lidar.front_obstacle_distance()
        self.telemetry.obstacle_distance_m = obstacle
        if (self.state.state in ACTIVE_STATES and obstacle is not None and
                obstacle <= self.config["driving"]["emergency_distance_m"]):
            self.emergency_stop("obstacle inside %.2fm" % obstacle)
        if self.state.state in ACTIVE_STATES and not self.bluetooth.connected:
            self.emergency_stop("Bluetooth disconnected")
        if self.state.state == "EMERGENCY":
            self._annotate(frame, detections)
            return
        if self.state.state == "MANUAL" and now > self._manual_deadline:
            self.vehicle.stop()
        elif self.state.state == "SELECT_NEAREST_OWNER":
            self._select_nearest_owner(frame, detections, now, cds_value)
        elif self.state.state == "REGISTER_OWNER":
            self._register(frame, detections, cds_value, now)
        elif self.state.state in ("FOLLOW_OWNER", "SEARCH_OWNER", "BLOCKED"):
            self._follow(frame, detections, obstacle, now, cds_value)
        self._annotate(frame, detections)

    def _reset_center_candidate(self):
        self._center_candidate_track_id = None
        self._center_candidate_since = None
        self._selection_hits.clear()
        self._selection_candidate_track_id = None
        self._selection_locked = False
        self._selection_missing_since = None
        self.telemetry.selection_hits = 0
        self.telemetry.selection_locked = False

    def _select_nearest_owner(self, frame, detections, now, cds_value):
        """Lock the visually nearest person, then collect clothing samples."""
        self.vehicle.stop()
        candidate = nearest_visual_person(detections)
        observed_track_id = None if candidate is None else candidate.track_id
        self._selection_hits.append(observed_track_id)
        if (observed_track_id is not None and
                observed_track_id != self._selection_candidate_track_id):
            self._selection_candidate_track_id = observed_track_id
            self.profile.begin(observed_track_id)

        sample_count = int(self.config["selection"].get("sample_count", 5))
        min_hits = int(self.config["selection"].get("min_hits", 3))
        hit_count = sum(track_id == self._selection_candidate_track_id
                        for track_id in self._selection_hits
                        if self._selection_candidate_track_id is not None)
        self.telemetry.selection_hits = hit_count
        self.telemetry.owner_status = "selecting-nearest"
        self.telemetry.selection_status = "candidate-%s hits-%s/%s" % (
            self._selection_candidate_track_id, hit_count, min_hits)
        if (self._selection_candidate_track_id is not None and
                len(self._selection_hits) >= sample_count and hit_count >= min_hits):
            self._selection_locked = True
            self.telemetry.selection_locked = True
            self.telemetry.selection_status = "locked-person-%s" % (
                self._selection_candidate_track_id,)
            self.state.transition("REGISTER_OWNER",
                                  "nearest person locked; collecting clothing pattern")

    def _restart_owner_selection(self, reason):
        self.profile = OwnerProfile()
        self._reset_center_candidate()
        self.state.transition("SELECT_NEAREST_OWNER", reason)
        self.telemetry.owner_status = "selecting-nearest"
        self.telemetry.selection_status = "selecting-nearest"

    def _register(self, frame, detections, cds_value, now):
        match = next((d for d in detections if d.track_id == self.profile.track_id), None)
        if match is None:
            if self._selection_missing_since is None:
                self._selection_missing_since = now
            loss_limit = float(self.config["selection"].get("locked_loss_seconds", 1.0))
            if now - self._selection_missing_since >= loss_limit:
                self._restart_owner_selection("locked person lost; selecting nearest again")
            return
        self._selection_missing_since = None
        self.profile.add_sample(match.feature,
                                self.encoder.brightness_variants(frame, match.box),
                                cds_value)
        needed = int(self.config["owner"]["registration_frames"])
        if len(self.profile.samples) >= needed:
            self._finish_registration()

    def _finish_registration(self):
        if self.profile.finalize():
            self.state.transition("FOLLOW_OWNER", "nearest owner clothing registered")
            self.telemetry.owner_status = "confirmed"
            self.telemetry.selection_status = "registered"
            self.telemetry.selection_locked = True
            self._lost_announced = False
            self._selection_hits.clear()

    def _follow(self, frame, detections, obstacle, now, cds_value):
        scored = []
        for detection in detections:
            scored.append((self.profile.score(detection, self.profile.track_id, cds_value),
                           detection))
        owner_status, owner = classify_candidates(scored, self.config["owner"]["confirm_score"],
                                                  self.config["owner"]["ambiguity_margin"])
        self.telemetry.owner_status = owner_status
        if owner is None:
            self.vehicle.stop()
            self.controller.reset_tracking()
            self.telemetry.owner_height_ratio = None
            self.telemetry.owner_distance_m = None
            if self.state.state != "SEARCH_OWNER":
                self.state.transition("SEARCH_OWNER", "owner temporarily lost")
                self._search_started = now
            elif now - self._search_started >= self.config["owner"]["search_seconds"]:
                self.state.transition("IDLE", "owner search timeout; press follow to register again")
                self.telemetry.selection_locked = False
                self.telemetry.selection_status = "restart-required"
                camera_position = self.camera_controller.reset()
                if camera_position is not None and self.camera_controller.enabled:
                    self.vehicle.pan_tilt(camera_position[0], camera_position[1])
                if not self._lost_announced:
                    self.tts.speak(self.config["tts"]["message_owner_lost"])
                    self._lost_announced = True
            return
        self.profile.track_id = owner.track_id
        distance = self.lidar.camera_x_distance(
            owner.center[0], frame.shape[1], self.camera_controller.view_angle_offset())
        # LiDAR owner distance is telemetry only. Missing returns must not stop following.
        self.telemetry.owner_distance_m = distance
        if obstacle is not None and obstacle < self.config["driving"]["stop_distance_m"]:
            self.vehicle.stop()
            if self.state.state != "BLOCKED":
                self.state.transition("BLOCKED", "path blocked")
            return
        if self.state.state != "FOLLOW_OWNER":
            self.state.transition("FOLLOW_OWNER", "owner confirmed")
        camera_position = self.camera_controller.command(
            owner.center[0], owner.center[1], frame.shape[1], frame.shape[0], now)
        if camera_position is not None:
            self.vehicle.pan_tilt(camera_position[0], camera_position[1])
        vehicle_target_x = self.camera_controller.compensated_target_x(
            owner.center[0], frame.shape[1])
        owner_height = max(0, owner.box[3] - owner.box[1])
        owner_height_ratio = min(1.0, float(owner_height) / max(1, frame.shape[0]))
        self.telemetry.owner_height_ratio = owner_height_ratio
        speed, steering = self.controller.command(
            vehicle_target_x, frame.shape[1], owner_height_ratio)
        self.vehicle.drive(speed, steering)

    def _annotate(self, frame, detections):
        import cv2
        for detection in detections:
            x1, y1, x2, y2 = detection.box
            color = (40, 210, 100) if detection.track_id == self.profile.track_id else (255, 170, 50)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, "person #%s %.2f" % (detection.track_id, detection.confidence),
                        (x1, max(18, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cv2.putText(frame, "%s | %s" % (self.state.state, self.state.reason), (12, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 230, 255), 2)
        with self._frame_lock:
            self.annotated_frame = frame
            self._annotated_monotonic = time.monotonic()

    def _record_latency(self, name, value_ms):
        """Record a bounded exponential moving average without storing samples."""
        current = float(getattr(self.telemetry, name, 0.0))
        value = max(0.0, float(value_ms))
        setattr(self.telemetry, name, value if current <= 0.0 else
                current * 0.8 + value * 0.2)

    def _cleanup_memory(self, now):
        """Bound long-running Python state without disrupting CUDA caches."""
        collected = gc.collect()
        self.telemetry.memory_collections += 1
        self.telemetry.memory_rss_mb = self._rss_mb()
        self._last_memory_cleanup = now
        LOG.info("memory maintenance collected=%s rss_mb=%.1f",
                 collected, self.telemetry.memory_rss_mb)

    @staticmethod
    def _rss_mb():
        try:
            with open("/proc/self/statm", "r") as handle:
                resident_pages = int(handle.read().split()[1])
            return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024.0 * 1024.0)
        except Exception:
            return 0.0
