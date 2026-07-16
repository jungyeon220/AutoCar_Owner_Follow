import json
import os
import tempfile
import unittest

from autocar.config import load_config
from autocar.adapters.cds import CdsAdapter
from autocar.adapters.vision import (PersonDetector, ensure_yolov5_font,
                                     load_local_hub_model,
                                     nearest_visual_person,
                                     prepare_legacy_yolov5)
from autocar.controller import CameraTrackingController, DrivingController
from autocar.models import Detection
from autocar.owner import OwnerProfile
from autocar.state_machine import StateMachine
from autocar.service import AutoCarService
from autocar.wave import HandWaveDetector, MotionWaveDetector, YPoseDetector


class ConfigTest(unittest.TestCase):
    def test_default_dimensions_are_multiple_of_32(self):
        config = load_config("does-not-exist.json")
        camera = config["camera"]
        for key in ("width", "height", "inference_width", "inference_height"):
            self.assertEqual(camera[key] % 32, 0)

    def test_camera_and_inference_dimensions_are_320_square(self):
        camera = load_config("does-not-exist.json")["camera"]
        self.assertEqual((camera["width"], camera["height"]), (320, 320))
        self.assertEqual((camera["inference_width"], camera["inference_height"]),
                         (320, 320))

    def test_invalid_dimension_is_rejected(self):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        try:
            json.dump({"camera": {"height": 360}}, handle)
            handle.close()
            with self.assertRaises(ValueError):
                load_config(handle.name)
        finally:
            os.unlink(handle.name)


class CdsAdapterTest(unittest.TestCase):
    def test_simulation_reader_uses_configured_value(self):
        adapter = CdsAdapter({"enabled": True, "simulation_value": 321}, True)
        adapter.start()
        self.assertTrue(adapter.ok)
        self.assertEqual(adapter.read(), 321.0)


class LegacyTorchHubTest(unittest.TestCase):
    def test_pytorch14_silu_compatibility_is_added(self):
        class Activation(object):
            pass

        class Modules(object):
            activation = Activation()

        class NN(object):
            Module = object
            modules = Modules()

        class FakeTorch(object):
            nn = NN()

            @staticmethod
            def sigmoid(value):
                return value

        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, "utils"))
            with open(os.path.join(repo, "utils", "__init__.py"), "w") as handle:
                handle.write("")
            with open(os.path.join(repo, "utils", "general.py"), "w") as handle:
                handle.write("def check_requirements(*args, **kwargs):\n    return False\n")
            prepare_legacy_yolov5(FakeTorch(), repo)
        self.assertTrue(hasattr(FakeTorch.nn, "SiLU"))
        self.assertTrue(hasattr(FakeTorch.nn.modules.activation, "SiLU"))

    def test_offline_font_is_copied_to_legacy_ultralytics_path(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "source.ttf")
            with open(source, "wb") as handle:
                handle.write(b"font" * 3000)
            home = os.path.join(root, "home")
            target = ensure_yolov5_font(home=home, candidates=(source,))
            self.assertTrue(os.path.isfile(target))
            self.assertGreater(os.path.getsize(target), 10000)

    def test_pytorch_without_source_parameter_loads_local_hubconf(self):
        class LegacyHub(object):
            @staticmethod
            def load(github, model, *args, **kwargs):
                raise AssertionError("legacy torch.hub.load must not be called")

        class LegacyTorch(object):
            hub = LegacyHub()

        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, "hubconf.py"), "w") as handle:
                handle.write("def custom(path=None):\n    return {'weights': path}\n")
            original_font = ensure_yolov5_font
            try:
                import autocar.adapters.vision as vision_module
                vision_module.ensure_yolov5_font = lambda: "font.ttf"
                original_prepare = vision_module.prepare_legacy_yolov5
                vision_module.prepare_legacy_yolov5 = lambda torch, path: None
                loaded = load_local_hub_model(LegacyTorch(), repo, "/models/person.pt")
            finally:
                vision_module.ensure_yolov5_font = original_font
                vision_module.prepare_legacy_yolov5 = original_prepare
        self.assertEqual(loaded["weights"], "/models/person.pt")


class PopPersonDetectorTest(unittest.TestCase):
    def test_pop_coco_results_keep_all_people_and_ignore_other_classes(self):
        detector = PersonDetector(
            {"backend": "pop", "tracking_iou": 0.3, "max_missing": 15},
            {"inference_width": 320, "inference_height": 320})

        class FakeModel(object):
            label_list = ["background", "person", "car"]

        detector.model = FakeModel()
        raw = [[
            {"label": 1, "confidence": 0.9, "bbox": [0.1, 0.2, 0.4, 0.9]},
            {"label": 2, "confidence": 0.8, "bbox": [0.5, 0.2, 0.9, 0.8]},
            {"label": 1, "confidence": 0.7, "bbox": [0.55, 0.1, 0.85, 0.95]},
        ]]
        people = detector._parse_pop_detections(raw, (320, 320, 3))
        self.assertEqual(len(people), 2)
        self.assertEqual(people[0].box, (32, 64, 128, 288))

    def test_service_uses_shared_pop_camera_for_pop_backend(self):
        service = AutoCarService(load_config("missing.json"))
        self.assertEqual(service.camera.backend, "pop")
        self.assertIs(service.detector.camera_adapter, service.camera)


class StateTest(unittest.TestCase):
    def test_follow_path(self):
        state = StateMachine()
        state.transition("IDLE", "ready")
        state.transition("SELECT_NEAREST_OWNER", "start")
        state.transition("REGISTER_OWNER", "marker")
        state.transition("FOLLOW_OWNER", "registered")
        self.assertEqual(state.state, "FOLLOW_OWNER")

    def test_invalid_transition(self):
        with self.assertRaises(ValueError):
            StateMachine().transition("FOLLOW_OWNER", "bad")


class WaveTest(unittest.TestCase):
    def test_y_pose_is_confirmed_after_stable_hold(self):
        detector = YPoseDetector(hold_seconds=1.2, sample_count=6, min_hits=5)
        points = {
            "left_shoulder": (-0.5, 1.0), "right_shoulder": (0.5, 1.0),
            "left_elbow": (-0.8, 0.7), "right_elbow": (0.8, 0.7),
            "left_wrist": (-1.0, 0.0), "right_wrist": (1.0, 0.0),
        }
        results = [detector.update(7, points, now=index * 0.25)
                   for index in range(6)]
        self.assertFalse(any(results[:-1]))
        self.assertTrue(results[-1])

    def test_one_raised_arm_is_not_y_pose(self):
        detector = YPoseDetector(hold_seconds=1.2, sample_count=6, min_hits=5)
        points = {
            "left_shoulder": (-0.5, 1.0), "right_shoulder": (0.5, 1.0),
            "left_elbow": (-0.8, 0.7), "right_elbow": (0.6, 1.2),
            "left_wrist": (-1.0, 0.0), "right_wrist": (0.6, 1.5),
        }
        self.assertFalse(any(detector.update(7, points, now=index * 0.25)
                             for index in range(8)))

    def test_front_facing_mirrored_coco_wrists_are_accepted(self):
        detector = YPoseDetector(hold_seconds=1.2, sample_count=6, min_hits=5)
        points = {
            "left_shoulder": (0.5, 1.0), "right_shoulder": (-0.5, 1.0),
            "left_elbow": (0.8, 0.7), "right_elbow": (-0.8, 0.7),
            "left_wrist": (1.0, 0.0), "right_wrist": (-1.0, 0.0),
        }
        results = [detector.update(8, points, now=index * 0.25)
                   for index in range(6)]
        self.assertTrue(results[-1])

    def test_y_pose_does_not_require_elbow_keypoints(self):
        detector = YPoseDetector(hold_seconds=1.2, sample_count=6, min_hits=4,
                                 min_wrist_raise_ratio=0.15,
                                 min_wrist_separation_ratio=1.2)
        points = {
            "left_shoulder": (0.5, 1.0), "right_shoulder": (-0.5, 1.0),
            "left_wrist": (1.0, 0.2), "right_wrist": (-1.0, 0.2),
        }
        results = [detector.update(9, points, now=index * 0.25)
                   for index in range(6)]
        self.assertTrue(results[-1])

    def test_horizontal_reversals_register(self):
        detector = HandWaveDetector(window_seconds=3, min_reversals=3, min_amplitude_ratio=.7)
        result = False
        for index, x in enumerate((0, 1, -1, 1, -1, 1, -1)):
            points = {"left_wrist": (x, 0), "left_shoulder": (-.5, 1),
                      "left_elbow": (-.5, .4), "right_shoulder": (.5, 1)}
            result = detector.update(4, points, now=index * .3) or result
        self.assertTrue(result)

    def test_stale_wave_and_motion_tracks_are_pruned(self):
        detector = HandWaveDetector(window_seconds=3)
        detector.history[(1, "left")] = __import__("collections").deque([(1.0, 0.0)])
        detector.history[(2, "left")] = __import__("collections").deque([(9.5, 0.0)])
        motion = MotionWaveDetector(detector)
        motion.previous = {1: object(), 2: object()}
        detector.prune([2], now=10.0)
        motion.prune([2])
        self.assertEqual(list(detector.history), [(2, "left")])
        self.assertEqual(list(motion.previous), [2])


class OwnerProfileTest(unittest.TestCase):
    def test_registration_samples_are_released_after_finalize(self):
        profile = OwnerProfile()
        profile.begin(1)
        profile.add_sample([1.0, 2.0], [(0.8, [0.8, 1.6])], 500)
        self.assertTrue(profile.finalize(0.3))
        self.assertEqual(profile.samples, [])
        self.assertEqual(profile.variant_samples, {})
        self.assertEqual(profile.cds_samples, [])
        self.assertEqual(profile.registered_cds, 500.0)
        self.assertIn(0.8, profile.brightness_features)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.controller = DrivingController(load_config("missing.json")["driving"])

    def test_stops_when_visual_owner_size_reaches_target(self):
        speed, steering = self.controller.command(320, 640, 0.72)
        self.assertEqual(speed, 0)

    def test_limits_speed_and_steering(self):
        speed, steering = self.controller.command(640, 640, 0.20)
        self.assertGreaterEqual(speed, 50)
        self.assertLessEqual(speed, 99)
        self.assertEqual(steering, 1.0)

    def test_visual_speed_does_not_require_lidar_distance(self):
        speed, steering = self.controller.command(320, 640, 0.20)
        self.assertGreater(speed, 0)
        self.assertEqual(steering, 0.0)

    def test_hard_stop_uses_current_box_before_ema_catches_up(self):
        self.controller.command(320, 640, 0.20)
        speed, unused = self.controller.command(320, 640, 0.90)
        self.assertEqual(speed, 0)


class CameraTrackingControllerTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config("missing.json")["camera_tracking"]
        self.controller = CameraTrackingController(self.config)

    def test_right_and_above_target_moves_pan_right_and_tilt_from_zero(self):
        command = self.controller.command(600, 50, 640, 480, now=1.0)
        self.assertIsNotNone(command)
        self.assertGreater(command[0], self.config["pan_center"])
        self.assertGreater(command[1], self.config["tilt_center"])

    def test_initial_tilt_center_is_zero_degrees(self):
        self.assertEqual(self.config["tilt_center"], 0.0)

    def test_center_deadband_does_not_move_camera(self):
        self.assertIsNone(self.controller.command(320, 240, 640, 480, now=1.0))

    def test_camera_yaw_is_preserved_for_vehicle_steering(self):
        self.controller.pan = 125.0
        compensated = self.controller.compensated_target_x(320, 640)
        self.assertGreater(compensated, 320)
        driving = DrivingController(load_config("missing.json")["driving"])
        speed, steering = driving.command(compensated, 640, 0.30)
        self.assertGreater(steering, 0.0)

    def test_camera_limits_are_enforced(self):
        self.controller.pan = self.config["pan_max"] - 1
        self.controller.tilt = self.config["tilt_min"] + 1
        command = self.controller.command(640, 480, 640, 480, now=1.0)
        self.assertLessEqual(command[0], self.config["pan_max"])
        self.assertGreaterEqual(command[1], self.config["tilt_min"])


class RuntimeSpeedLimitTest(unittest.TestCase):
    def setUp(self):
        self.service = AutoCarService(load_config("missing.json"))

    def test_authenticated_runtime_limit_updates_follow_and_manual_speed(self):
        self.service.set_speed_limit(50)
        self.assertEqual(self.service.config["driving"]["max_speed"], 50)
        self.assertEqual(self.service.config["driving"]["manual_max_speed"], 50)

    def test_runtime_limit_rejects_value_above_dashboard_cap(self):
        with self.assertRaises(ValueError):
            self.service.set_speed_limit(100)

    def test_runtime_limit_rejects_value_below_fixed_minimum(self):
        with self.assertRaises(ValueError):
            self.service.set_speed_limit(49)

    def test_dashboard_camera_tilt_updates_runtime_center(self):
        self.service.set_camera_tilt(25)
        self.assertEqual(self.service.vehicle.tilt, 25.0)
        self.assertEqual(self.service.camera_controller.tilt, 25.0)
        self.assertEqual(self.service.config["camera_tracking"]["tilt_center"], 25.0)

    def test_dashboard_camera_tilt_rejects_out_of_range_value(self):
        with self.assertRaises(ValueError):
            self.service.set_camera_tilt(91)

    def test_latency_uses_bounded_exponential_average(self):
        self.service._record_latency("inference_latency_ms", 100.0)
        self.service._record_latency("inference_latency_ms", 200.0)
        self.assertAlmostEqual(self.service.telemetry.inference_latency_ms, 120.0)

    def test_follow_request_starts_nearest_person_selection(self):
        self.service.state.transition("IDLE", "ready")
        self.service.bluetooth.connected = True
        self.service.telemetry.camera_ok = True
        self.service.lidar.ok = True
        self.service.request_follow()
        self.assertEqual(self.service.state.state, "SELECT_NEAREST_OWNER")
        self.assertIsNone(self.service.profile.track_id)

    def test_nearest_person_three_of_five_is_locked_for_registration(self):
        import numpy as np
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        nearest = Detection((180, 30, 460, 620), 0.9, track_id=7,
                            feature=np.asarray([1.0, 0.0]))
        farther = Detection((20, 180, 160, 500), 0.9, track_id=8,
                            feature=np.asarray([0.0, 1.0]))
        self.service.encoder.brightness_variants = lambda unused_frame, unused_box: []
        self.service.state.transition("IDLE", "ready")
        self.service.state.transition("SELECT_NEAREST_OWNER", "start")
        for now in (1.0, 1.2, 1.4, 1.6, 1.8):
            self.service._select_nearest_owner(
                frame, [farther, nearest], now, 500.0)
        self.assertEqual(self.service.state.state, "REGISTER_OWNER")
        self.assertEqual(self.service.profile.track_id, 7)
        self.assertTrue(self.service.telemetry.selection_locked)

    def test_other_person_does_not_replace_locked_registration_target(self):
        import numpy as np
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        locked = Detection((200, 100, 400, 580), 0.9, track_id=7,
                           feature=np.asarray([1.0, 0.0]))
        newcomer = Detection((0, 0, 630, 640), 0.9, track_id=9,
                             feature=np.asarray([0.0, 1.0]))
        self.service.encoder.brightness_variants = lambda unused_frame, unused_box: []
        self.service.state.transition("IDLE", "ready")
        self.service.state.transition("SELECT_NEAREST_OWNER", "start")
        self.service.state.transition("REGISTER_OWNER", "locked")
        self.service.profile.begin(7)
        self.service._selection_locked = True
        self.service._register(frame, [newcomer, locked], 500.0, 2.0)
        self.assertEqual(self.service.profile.track_id, 7)

    def test_locked_candidate_loss_for_one_second_restarts_selection(self):
        import numpy as np
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        self.service.state.transition("IDLE", "ready")
        self.service.state.transition("SELECT_NEAREST_OWNER", "start")
        self.service.state.transition("REGISTER_OWNER", "locked")
        self.service.profile.begin(7)
        self.service._register(frame, [], 500.0, 1.0)
        self.assertEqual(self.service.state.state, "REGISTER_OWNER")
        self.service._register(frame, [], 500.0, 2.1)
        self.assertEqual(self.service.state.state, "SELECT_NEAREST_OWNER")

    def test_lost_owner_is_reidentified_by_clothing_without_aruco_scan(self):
        import numpy as np
        frame = np.zeros((320, 320, 3), dtype=np.uint8)
        self.service.profile.feature = np.asarray([1.0, 0.0])
        self.service.profile.track_id = 7
        candidate = Detection((120, 60, 210, 260), 0.9, track_id=11,
                              feature=np.asarray([1.0, 0.0]))
        self.service.state.transition("IDLE", "ready")
        self.service.state.transition("SELECT_NEAREST_OWNER", "select")
        self.service.state.transition("FOLLOW_OWNER", "registered")
        self.service.state.transition("SEARCH_OWNER", "lost")
        self.service._search_started = 1.0
        self.service._follow(frame, [candidate], None, 2.0, 500.0)
        self.assertEqual(self.service.state.state, "FOLLOW_OWNER")
        self.assertEqual(self.service.profile.track_id, 11)

    def test_clothing_search_timeout_stops_until_dashboard_restart(self):
        import numpy as np
        frame = np.zeros((320, 320, 3), dtype=np.uint8)
        self.service.state.transition("IDLE", "ready")
        self.service.state.transition("SELECT_NEAREST_OWNER", "select")
        self.service.state.transition("FOLLOW_OWNER", "registered")
        self.service.state.transition("SEARCH_OWNER", "lost")
        self.service._search_started = 1.0
        self.service._follow(frame, [], None, 6.1, 500.0)
        self.assertEqual(self.service.state.state, "IDLE")


class NearestVisualPersonTest(unittest.TestCase):
    def test_tallest_person_box_is_selected_as_nearest(self):
        small = Detection((200, 200, 400, 480), 0.9, track_id=1)
        large = Detection((10, 20, 500, 620), 0.9, track_id=2)
        self.assertEqual(nearest_visual_person([small, large]).track_id, 2)


if __name__ == "__main__":
    unittest.main()
