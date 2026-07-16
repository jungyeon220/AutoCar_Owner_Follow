import copy
import json
import os


DEFAULTS = {
    "runtime": {"simulation": True, "loop_hz": 8, "log_level": "INFO",
                "memory_cleanup_seconds": 300.0},
    "camera": {"width": 320, "height": 320, "inference_width": 320,
               "inference_height": 320, "fps": 30, "flip_method": 0},
    "camera_tracking": {"enabled": True, "pan_center": 90.0, "tilt_center": 0.0,
                        "pan_min": 20.0, "pan_max": 160.0,
                        "tilt_min": 0.0, "tilt_max": 90.0,
                        "pan_gain_deg": 6.0, "tilt_gain_deg": 4.0,
                        "max_step_deg": 3.0, "deadband_x": 0.12,
                        "deadband_y": 0.12, "update_interval_seconds": 0.12,
                        "pan_direction": 1.0, "tilt_direction": -1.0},
    "detector": {"backend": "pop", "repo": "vendor/yolov5",
                 "weights": "models/yolov5n.pt", "confidence": 0.45,
                 "iou": 0.45, "device": "cuda:0"},
    "pose": {"enabled": False, "backend": "trt_pose",
             "model": "models/resnet18_baseline_att_224x224_A_epoch_249.pth",
             "device": "cuda:0", "input_size": 224,
             "crop_padding_ratio": 0.15, "keypoint_threshold": 0.10,
             "inference_fps": 4.0,
             "gesture_timeout_seconds": 5.0,
             "y_pose_hold_seconds": 1.2, "y_pose_sample_count": 6,
             "y_pose_min_hits": 4, "y_pose_min_wrist_raise_ratio": 0.15,
             "y_pose_min_wrist_separation_ratio": 1.2,
             "y_pose_max_elbow_drop_ratio": 0.25},
    "aruco": {"enabled": False, "dictionary": "DICT_4X4_50", "owner_id": 0,
              "scan_fps": 8.0, "sample_count": 5, "min_hits": 3,
              "min_side_px": 50.0, "timeout_seconds": 5.0,
              "bbox_margin_ratio": 0.10},
    "selection": {"sample_count": 5, "min_hits": 3,
                  "locked_loss_seconds": 1.0},
    "owner": {"registration_frames": 20, "confirm_score": 0.70,
              "ambiguity_margin": 0.12, "search_seconds": 5.0,
              "center_registration_seconds": 1.5,
              "center_tolerance_x": 0.18, "center_tolerance_y": 0.30},
    "driving": {"max_speed": 99, "manual_max_speed": 99,
                "dashboard_max_speed": 99, "min_follow_speed": 50,
                "target_distance_m": 0.3, "stop_distance_m": 0.2,
                "emergency_distance_m": 0.1, "steering_kp": 1.4,
                "steering_deadband": 0.08,
                "target_owner_height_ratio": 0.72,
                "hard_stop_owner_height_ratio": 0.88,
                "visual_size_deadband": 0.03,
                "visual_size_ema_alpha": 0.25,
                "visual_speed_kp": 80.0},
    "lidar": {"enabled": True, "port": "auto", "baudrates": [115200, 256000],
              "front_angle_deg": 0.0, "clockwise": False,
              "camera_fov_deg": 160.0, "association_window_deg": 5.0},
    "cds": {"enabled": True, "channel": 7, "poll_seconds": 0.25,
            "simulation_value": 512.0},
    "bluetooth": {"enabled": False, "owner_mac": "", "poll_seconds": 1.0},
    "tts": {"enabled": True, "backend": "piper", "piper_command": "piper",
            "model": "models/ko_KR-kss-medium.onnx",
            "config": "models/ko_KR-kss-medium.onnx.json",
            "message_owner_lost": "사용자를 찾을 수 없습니다."},
    "web": {"host": "0.0.0.0", "port": 8080, "stream_fps": 5,
            "secret_key_env": "KNU_RC_SECRET_KEY", "user_env": "KNU_RC_USER",
            "password_env": "KNU_RC_PASSWORD"}
}


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _validate_multiple_of_32(name, value):
    if not isinstance(value, int) or value <= 0 or value % 32 != 0:
        raise ValueError("%s must be a positive multiple of 32 (got %r)" % (name, value))


def load_config(path=None):
    config = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("KNU_RC_CONFIG", "config/autocar.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            _merge(config, json.load(handle))
    for field in ("width", "height", "inference_width", "inference_height"):
        _validate_multiple_of_32("camera.%s" % field, config["camera"][field])
    cleanup_seconds = config["runtime"].get("memory_cleanup_seconds", 300.0)
    if not isinstance(cleanup_seconds, (int, float)) or cleanup_seconds < 30:
        raise ValueError("runtime.memory_cleanup_seconds must be at least 30 seconds")
    loop_hz = config["runtime"].get("loop_hz", 8)
    if not isinstance(loop_hz, (int, float)) or loop_hz <= 0:
        raise ValueError("runtime.loop_hz must be positive")
    camera_fps = config["camera"].get("fps", 30)
    if not isinstance(camera_fps, (int, float)) or camera_fps <= 0:
        raise ValueError("camera.fps must be positive")
    aruco = config["aruco"]
    if aruco.get("enabled", True):
        if not isinstance(aruco.get("owner_id"), int) or aruco["owner_id"] < 0:
            raise ValueError("aruco.owner_id must be a non-negative integer")
        if not isinstance(aruco.get("scan_fps"), (int, float)) or aruco["scan_fps"] <= 0:
            raise ValueError("aruco.scan_fps must be positive")
        samples = aruco.get("sample_count", 5)
        hits = aruco.get("min_hits", 3)
        if not isinstance(samples, int) or not isinstance(hits, int) or not 1 <= hits <= samples:
            raise ValueError("aruco hits must satisfy 1 <= min_hits <= sample_count")
    selection = config["selection"]
    samples = selection.get("sample_count", 5)
    hits = selection.get("min_hits", 3)
    if not isinstance(samples, int) or not isinstance(hits, int) or not 1 <= hits <= samples:
        raise ValueError("selection hits must satisfy 1 <= min_hits <= sample_count")
    if float(selection.get("locked_loss_seconds", 1.0)) <= 0:
        raise ValueError("selection.locked_loss_seconds must be positive")
    if not 0 <= config["driving"]["max_speed"] <= 99:
        raise ValueError("driving.max_speed must be between 0 and 99")
    dashboard_cap = config["driving"].get("dashboard_max_speed", 30)
    if not isinstance(dashboard_cap, int) or not 0 <= dashboard_cap <= 99:
        raise ValueError("driving.dashboard_max_speed must be between 0 and 99")
    if config["driving"]["max_speed"] > dashboard_cap:
        raise ValueError("driving.max_speed cannot exceed dashboard_max_speed")
    minimum_speed = config["driving"].get("min_follow_speed", 50)
    if not isinstance(minimum_speed, int) or not 0 <= minimum_speed <= 99:
        raise ValueError("driving.min_follow_speed must be between 0 and 99")
    if config["driving"]["max_speed"] < minimum_speed:
        raise ValueError("driving.max_speed cannot be below min_follow_speed")
    if config["driving"]["emergency_distance_m"] <= 0:
        raise ValueError("emergency distance must be positive")
    if not (config["driving"]["emergency_distance_m"] <
            config["driving"]["stop_distance_m"] <
            config["driving"]["target_distance_m"]):
        raise ValueError("driving distances must satisfy emergency < stop < target")
    target_ratio = config["driving"].get("target_owner_height_ratio", 0.72)
    hard_stop_ratio = config["driving"].get("hard_stop_owner_height_ratio", 0.88)
    if not (0.0 < target_ratio < hard_stop_ratio <= 1.0):
        raise ValueError("owner height ratios must satisfy 0 < target < hard stop <= 1")
    tracking = config.get("camera_tracking", {})
    if tracking.get("pan_min", 0) > tracking.get("pan_center", 90):
        raise ValueError("camera_tracking.pan_center must be inside PAN limits")
    if tracking.get("pan_center", 90) > tracking.get("pan_max", 180):
        raise ValueError("camera_tracking.pan_center must be inside PAN limits")
    if tracking.get("tilt_min", 0) > tracking.get("tilt_center", 0):
        raise ValueError("camera_tracking.tilt_center must be inside TILT limits")
    if tracking.get("tilt_center", 0) > tracking.get("tilt_max", 90):
        raise ValueError("camera_tracking.tilt_center must be inside TILT limits")
    return config
