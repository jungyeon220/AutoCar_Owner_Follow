class DrivingController(object):
    def __init__(self, config):
        self.config = config
        self._smoothed_owner_size = None

    def reset_tracking(self):
        self._smoothed_owner_size = None

    def command(self, target_center_x, image_width, owner_size_ratio):
        """Steer from image/PAN direction and drive from visual owner size only."""
        error = (float(target_center_x) - image_width / 2.0) / (image_width / 2.0)
        deadband = self.config.get("steering_deadband", 0.08)
        steering = 0.0 if abs(error) <= deadband else error * self.config.get("steering_kp", 1.4)
        steering = max(-1.0, min(1.0, steering))

        if owner_size_ratio is None or owner_size_ratio <= 0.0:
            return 0, steering

        alpha = float(self.config.get("visual_size_ema_alpha", 0.25))
        alpha = max(0.01, min(1.0, alpha))
        if self._smoothed_owner_size is None:
            self._smoothed_owner_size = float(owner_size_ratio)
        else:
            self._smoothed_owner_size = (
                self._smoothed_owner_size * (1.0 - alpha) +
                float(owner_size_ratio) * alpha)

        target = float(self.config.get("target_owner_height_ratio", 0.72))
        hard_stop = float(self.config.get("hard_stop_owner_height_ratio", 0.88))
        size_deadband = float(self.config.get("visual_size_deadband", 0.03))
        if (float(owner_size_ratio) >= hard_stop or
                self._smoothed_owner_size >= target - size_deadband):
            return 0, steering

        visual_error = target - self._smoothed_owner_size
        maximum = int(self.config.get("max_speed", 99))
        speed = int(max(0, min(maximum,
                               visual_error * self.config.get("visual_speed_kp", 80.0))))
        if abs(error) > 0.4:
            speed = int(speed * 0.4)
        if speed > 0:
            speed = max(int(self.config.get("min_follow_speed", 50)), speed)
            speed = min(maximum, speed)
        return speed, steering


class CameraTrackingController(object):
    """Rate-limited PAN/TILT controller driven by image-center error."""
    def __init__(self, config):
        self.config = config
        self.pan = float(config.get("pan_center", 90.0))
        self.tilt = float(config.get("tilt_center", 45.0))
        self.last_update = 0.0

    @property
    def enabled(self):
        return bool(self.config.get("enabled", True))

    def reset(self):
        self.pan = float(self.config.get("pan_center", 90.0))
        self.tilt = float(self.config.get("tilt_center", 45.0))
        self.last_update = 0.0
        return self.pan, self.tilt

    def command(self, target_x, target_y, image_width, image_height, now):
        if not self.enabled:
            return None
        interval = float(self.config.get("update_interval_seconds", 0.12))
        if self.last_update and now - self.last_update < interval:
            return None
        error_x = (float(target_x) - image_width / 2.0) / (image_width / 2.0)
        error_y = (float(target_y) - image_height / 2.0) / (image_height / 2.0)
        delta_pan = 0.0
        delta_tilt = 0.0
        if abs(error_x) > float(self.config.get("deadband_x", 0.12)):
            delta_pan = (error_x * float(self.config.get("pan_gain_deg", 6.0)) *
                         float(self.config.get("pan_direction", 1.0)))
        if abs(error_y) > float(self.config.get("deadband_y", 0.12)):
            delta_tilt = (error_y * float(self.config.get("tilt_gain_deg", 4.0)) *
                          float(self.config.get("tilt_direction", -1.0)))
        max_step = float(self.config.get("max_step_deg", 3.0))
        delta_pan = max(-max_step, min(max_step, delta_pan))
        delta_tilt = max(-max_step, min(max_step, delta_tilt))
        if delta_pan == 0.0 and delta_tilt == 0.0:
            return None
        self.pan = max(float(self.config.get("pan_min", 20.0)),
                       min(float(self.config.get("pan_max", 160.0)), self.pan + delta_pan))
        self.tilt = max(float(self.config.get("tilt_min", 0.0)),
                        min(float(self.config.get("tilt_max", 90.0)), self.tilt + delta_tilt))
        self.last_update = now
        return self.pan, self.tilt

    def view_angle_offset(self):
        """Camera yaw relative to the vehicle front, positive to image right."""
        return ((self.pan - float(self.config.get("pan_center", 90.0))) *
                float(self.config.get("pan_direction", 1.0)))

    def compensated_target_x(self, target_x, image_width):
        """Convert image error plus camera yaw into vehicle-relative direction."""
        center = float(self.config.get("pan_center", 90.0))
        left_span = max(center - float(self.config.get("pan_min", 20.0)), 1.0)
        right_span = max(float(self.config.get("pan_max", 160.0)) - center, 1.0)
        offset = self.view_angle_offset()
        normalized = offset / (right_span if offset >= 0 else left_span)
        normalized = max(-1.0, min(1.0, normalized))
        return float(target_x) + normalized * (image_width / 2.0)
