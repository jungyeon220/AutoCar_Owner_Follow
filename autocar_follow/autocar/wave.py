import collections
import time


class YPoseDetector(object):
    """Confirm a stable two-arm overhead Y pose from upper-body joints."""
    def __init__(self, hold_seconds=1.2, sample_count=6, min_hits=5,
                 min_wrist_raise_ratio=0.35, min_wrist_separation_ratio=1.4,
                 max_elbow_drop_ratio=0.25):
        self.hold_seconds = float(hold_seconds)
        self.sample_count = int(sample_count)
        self.min_hits = int(min_hits)
        self.min_wrist_raise_ratio = float(min_wrist_raise_ratio)
        self.min_wrist_separation_ratio = float(min_wrist_separation_ratio)
        self.max_elbow_drop_ratio = float(max_elbow_drop_ratio)
        self.history = {}
        self.last_reason = {}

    def reset(self, track_id=None):
        if track_id is None:
            self.history = {}
            self.last_reason = {}
        else:
            self.history.pop(track_id, None)
            self.last_reason.pop(track_id, None)

    def prune(self, active_track_ids, now=None):
        active = set(active_track_ids)
        now = time.time() if now is None else now
        for track_id in list(self.history):
            points = self.history[track_id]
            while points and now - points[0][0] > self.hold_seconds * 1.5:
                points.popleft()
            if track_id not in active or not points:
                self.history.pop(track_id, None)
                self.last_reason.pop(track_id, None)

    def update(self, track_id, keypoints, now=None):
        now = time.time() if now is None else now
        passed, reason = self._evaluate(keypoints)
        self.last_reason[track_id] = reason
        points = self.history.setdefault(
            track_id, collections.deque(maxlen=self.sample_count))
        points.append((now, passed))
        if len(points) < self.sample_count or not passed:
            return False
        positive_times = [timestamp for timestamp, ok in points if ok]
        if len(positive_times) < self.min_hits:
            return False
        minimum_span = self.hold_seconds * 0.8
        if positive_times[-1] - positive_times[0] < minimum_span:
            return False
        self.reset(track_id)
        return True

    def reason(self, track_id):
        return self.last_reason.get(track_id, "collecting")

    def _evaluate(self, keypoints):
        names = ("left_shoulder", "right_shoulder", "left_wrist", "right_wrist")
        if not all(name in keypoints for name in names):
            missing = next(name for name in names if name not in keypoints)
            return False, "missing-" + missing
        left_shoulder, right_shoulder, left_wrist, right_wrist = (
            keypoints[name] for name in names)
        shoulder_width = abs(right_shoulder[0] - left_shoulder[0])
        if shoulder_width <= 1e-6:
            return False, "invalid-shoulders"
        center_x = (left_shoulder[0] + right_shoulder[0]) / 2.0
        wrist_raise = shoulder_width * self.min_wrist_raise_ratio
        if left_wrist[1] > left_shoulder[1] - wrist_raise:
            return False, "left-wrist-not-high"
        if right_wrist[1] > right_shoulder[1] - wrist_raise:
            return False, "right-wrist-not-high"
        wrist_min_x = min(left_wrist[0], right_wrist[0])
        wrist_max_x = max(left_wrist[0], right_wrist[0])
        # COCO left/right labels are the person's anatomical sides. For a
        # person facing the camera they appear mirrored in image coordinates.
        if not wrist_min_x < center_x < wrist_max_x:
            return False, "wrists-not-opposite"
        if wrist_max_x - wrist_min_x < (
                shoulder_width * self.min_wrist_separation_ratio):
            return False, "wrists-too-close"
        return True, "matched"


class HandWaveDetector(object):
    """Detect a left or right arm waving from shoulder/elbow/wrist joints.

    Keypoints are normalized or pixel coordinates. The amplitude is normalized by
    shoulder width, so it remains stable as the owner moves toward the camera.
    """
    def __init__(self, window_seconds=2.5, min_reversals=3, min_amplitude_ratio=0.7):
        self.window_seconds = float(window_seconds)
        self.min_reversals = int(min_reversals)
        self.min_amplitude_ratio = float(min_amplitude_ratio)
        self.history = {}

    def reset(self, track_id=None):
        if track_id is None:
            self.history = {}
        else:
            for key in list(self.history):
                if key[0] == track_id:
                    self.history.pop(key, None)

    def prune(self, active_track_ids, now=None):
        """Discard histories for tracks that are no longer visible."""
        active = set(active_track_ids)
        now = time.time() if now is None else now
        for key in list(self.history):
            points = self.history[key]
            while points and now - points[0][0] > self.window_seconds:
                points.popleft()
            if key[0] not in active or not points:
                self.history.pop(key, None)

    def update(self, track_id, keypoints, now=None):
        now = time.time() if now is None else now
        if not all(name in keypoints for name in ("left_shoulder", "right_shoulder")):
            return False
        left = keypoints["left_shoulder"]
        right = keypoints["right_shoulder"]
        shoulder_width = max(abs(right[0] - left[0]), 1e-6)
        center_x = (left[0] + right[0]) / 2.0
        for side in ("left", "right"):
            required = (side + "_shoulder", side + "_elbow", side + "_wrist")
            if not all(name in keypoints for name in required):
                continue
            shoulder, elbow, wrist = [keypoints[name] for name in required]
            # A valid wave must be a raised arm, not whole-body horizontal motion.
            if wrist[1] >= shoulder[1]:
                continue
            if elbow[1] > shoulder[1] + shoulder_width * 0.65:
                continue
            position = (wrist[0] - center_x) / shoulder_width
            if self._update_arm((track_id, side), position, now):
                self.reset(track_id)
                return True
        return False

    def _update_arm(self, key, position, now):
        points = self.history.setdefault(key, collections.deque())
        points.append((now, position))
        while points and now - points[0][0] > self.window_seconds:
            points.popleft()
        if len(points) < 6:
            return False
        values = [p[1] for p in points]
        if max(values) - min(values) < self.min_amplitude_ratio:
            return False
        signs = []
        for previous, current in zip(values, values[1:]):
            delta = current - previous
            if abs(delta) > 0.08:
                signs.append(1 if delta > 0 else -1)
        reversals = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
        return reversals >= self.min_reversals


class MotionWaveDetector(object):
    """Pose-free fallback using horizontal motion in the upper person crop."""
    def __init__(self, wave_detector):
        self.wave_detector = wave_detector
        self.previous = {}

    def reset(self, track_id=None):
        if track_id is None:
            self.previous = {}
        else:
            self.previous.pop(track_id, None)

    def prune(self, active_track_ids):
        active = set(active_track_ids)
        for track_id in list(self.previous):
            if track_id not in active:
                self.previous.pop(track_id, None)

    def update(self, track_id, frame, box, now=None):
        import cv2
        import numpy as np
        x1, y1, x2, y2 = box
        width, height = x2 - x1, y2 - y1
        if width < 30 or height < 60:
            return False
        upper = frame[max(0, y1):max(0, y1 + int(height * 0.55)), max(0, x1):max(0, x2)]
        if upper.size == 0:
            return False
        gray = cv2.resize(cv2.cvtColor(upper, cv2.COLOR_BGR2GRAY), (96, 96))
        previous = self.previous.get(track_id)
        self.previous[track_id] = gray
        if previous is None:
            return False
        difference = cv2.absdiff(gray, previous)
        mask = difference > 28
        ys, xs = np.where(mask)
        if len(xs) < 45:
            return False
        motion_x = x1 + (float(np.median(xs)) / 95.0) * width
        keypoints = {
            "left_wrist": (motion_x, y1),
            "left_shoulder": (x1 + width * 0.25, y1 + height * 0.5),
            "right_shoulder": (x1 + width * 0.75, y1 + height * 0.5)
        }
        return self.wave_detector.update(track_id, keypoints, now=now)
