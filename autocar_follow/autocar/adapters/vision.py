import logging
import os
import importlib.util
import inspect
import shutil
import sys

import numpy as np

from autocar.models import Detection
from autocar.adapters.camera import letterbox


LOG = logging.getLogger(__name__)


def ensure_yolov5_font(home=None, candidates=None):
    """Provision YOLOv5's legacy Arial path without a runtime download."""
    home = home or os.path.expanduser("~")
    target = os.path.join(home, ".config", "Ultralytics", "Arial.ttf")
    if os.path.isfile(target) and os.path.getsize(target) > 10000:
        return target
    candidates = candidates or (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    )
    source = next((path for path in candidates if os.path.isfile(path)), None)
    if source is None:
        raise RuntimeError("no local TrueType font available for YOLOv5")
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    shutil.copyfile(source, target)
    LOG.info("provisioned offline YOLOv5 font %s from %s", target, source)
    return target


def prepare_legacy_yolov5(torch, repo):
    """Provide YOLOv5 v6 shims while preserving JetPack's PyTorch 1.4."""
    if not hasattr(torch.nn.modules.activation, "SiLU"):
        class Torch14SiLU(torch.nn.Module):
            def __init__(self, inplace=False):
                super(Torch14SiLU, self).__init__()
                self.inplace = inplace

            def forward(self, value):
                return value * torch.sigmoid(value)

        torch.nn.modules.activation.SiLU = Torch14SiLU
        torch.nn.SiLU = Torch14SiLU
        LOG.info("enabled PyTorch 1.4 SiLU compatibility for YOLOv5")

    # YOLOv5 v6 otherwise invokes pip from inside the vehicle process. Never
    # replace JetPack's NVIDIA PyTorch wheel at runtime.
    os.environ["YOLOv5_AUTOINSTALL"] = "false"
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        general = importlib.import_module("utils.general")
        general.check_requirements = lambda *args, **kwargs: True
    except Exception:
        LOG.exception("could not disable YOLOv5 requirements auto-install")
        raise


def load_local_hub_model(torch, repo, weights):
    """Load a local hubconf on PyTorch versions predating source='local'."""
    ensure_yolov5_font()
    parameters = inspect.signature(torch.hub.load).parameters
    if "source" in parameters:
        return torch.hub.load(repo, "custom", path=weights, source="local")

    hubconf_path = os.path.join(repo, "hubconf.py")
    if not os.path.isfile(hubconf_path):
        raise RuntimeError("local YOLOv5 hubconf.py missing: %s" % hubconf_path)
    prepare_legacy_yolov5(torch, repo)
    module_name = "autocar_yolov5_hubconf"
    spec = importlib.util.spec_from_file_location(module_name, hubconf_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load local YOLOv5 hubconf: %s" % hubconf_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    custom = getattr(module, "custom", None)
    if custom is None:
        raise RuntimeError("YOLOv5 hubconf does not define custom()")
    try:
        return custom(path=weights)
    except TypeError:
        # Some older YOLOv5 hubconf versions use a positional weights argument.
        return custom(weights)


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = ((ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
    return 0.0 if union <= 0 else float(intersection) / union


class IoUTracker(object):
    def __init__(self, threshold=0.3, max_missing=15):
        self.threshold = threshold
        self.max_missing = max_missing
        self.tracks = {}
        self.next_id = 1

    def update(self, detections):
        unmatched = set(self.tracks.keys())
        for detection in detections:
            candidates = [(iou(detection.box, self.tracks[track_id][0]), track_id)
                          for track_id in unmatched]
            score, track_id = max(candidates, default=(0.0, None))
            if track_id is None or score < self.threshold:
                track_id = self.next_id
                self.next_id += 1
            else:
                unmatched.discard(track_id)
            detection.track_id = track_id
            self.tracks[track_id] = (detection.box, 0)
        for track_id in list(unmatched):
            box, missing = self.tracks[track_id]
            if missing + 1 > self.max_missing:
                del self.tracks[track_id]
            else:
                self.tracks[track_id] = (box, missing + 1)
        return detections


class PersonDetector(object):
    """Person detector with the Hanback POP example as the primary backend."""
    def __init__(self, config, camera_config, simulation=False, camera_adapter=None):
        self.config = config
        self.camera_config = camera_config
        self.backend = str(config.get("backend", "pop")).lower()
        self.simulation = simulation or self.backend == "mock"
        self.camera_adapter = camera_adapter
        self.model = None
        self.tracker = IoUTracker(
            float(config.get("tracking_iou", 0.3)),
            int(config.get("max_missing", 15)))

    def start(self):
        if self.simulation:
            return
        if self.backend == "pop":
            from pop import Pilot
            camera = None if self.camera_adapter is None else self.camera_adapter.pop_camera
            if camera is None:
                raise RuntimeError("POP detector requires the shared Pilot.Camera instance")
            self.model = Pilot.Object_Follow(camera)
            if getattr(self.model, "camera", None) is None:
                raise RuntimeError("Pilot.Object_Follow rejected the shared camera")
            self.model.load_model()
            LOG.info("loaded Hanback Pilot.Object_Follow model")
            return
        if self.backend not in ("yolov5", "torch"):
            raise RuntimeError("unsupported detector backend: %s" % self.backend)
        import torch
        repo, weights = self.config["repo"], self.config["weights"]
        if not os.path.isdir(repo):
            raise RuntimeError("local YOLOv5 repository missing: %s" % repo)
        if not os.path.isfile(weights):
            raise RuntimeError("YOLO weights missing: %s" % weights)
        self.model = load_local_hub_model(torch, repo, weights)
        self.model.conf = float(self.config.get("confidence", 0.45))
        self.model.iou = float(self.config.get("iou", 0.45))
        self.model.classes = [0]
        self.model.to(self.config.get("device", "cuda:0"))
        self.model.eval()

    def detect(self, frame):
        if self.simulation:
            return []
        if self.backend == "pop":
            raw = self.model.detect(
                image=frame.copy(), index=None,
                threshold=float(self.config.get("confidence", 0.45)), show=False)
            return self.tracker.update(self._parse_pop_detections(raw, frame.shape))
        width = self.camera_config["inference_width"]
        height = self.camera_config["inference_height"]
        inference_frame, ratio, padding = letterbox(frame, width, height)
        size = max(width, height)
        results = self.model(inference_frame, size=size)
        rows = results.xyxy[0].detach().cpu().numpy()
        detections = []
        frame_height, frame_width = frame.shape[:2]
        for row in rows:
            if int(row[5]) != 0:
                continue
            x1 = max(0, min(frame_width, (row[0] - padding[0]) / ratio))
            y1 = max(0, min(frame_height, (row[1] - padding[1]) / ratio))
            x2 = max(0, min(frame_width, (row[2] - padding[0]) / ratio))
            y2 = max(0, min(frame_height, (row[3] - padding[1]) / ratio))
            detections.append(Detection((x1, y1, x2, y2), row[4]))
        return self.tracker.update(detections)

    def _parse_pop_detections(self, raw, frame_shape):
        """Convert POP COCO normalized boxes into common person detections."""
        rows = raw[0] if isinstance(raw, (list, tuple)) and len(raw) == 1 else raw
        if rows is None:
            return []
        labels = getattr(self.model, "label_list", ())
        frame_height, frame_width = frame_shape[:2]
        detections = []
        for row in rows:
            try:
                label_index = int(row["label"])
                label = labels[label_index] if 0 <= label_index < len(labels) else None
                if label != "person":
                    continue
                bbox = row["bbox"]
                x1 = max(0, min(frame_width, float(bbox[0]) * frame_width))
                y1 = max(0, min(frame_height, float(bbox[1]) * frame_height))
                x2 = max(0, min(frame_width, float(bbox[2]) * frame_width))
                y2 = max(0, min(frame_height, float(bbox[3]) * frame_height))
                if x2 <= x1 or y2 <= y1:
                    continue
                detections.append(Detection(
                    (x1, y1, x2, y2), float(row.get("confidence", 0.0))))
            except (KeyError, TypeError, ValueError, IndexError):
                LOG.warning("ignored malformed POP detection: %r", row)
        return detections


class ArucoDetector(object):
    """OpenCV ArUco adapter used only for initial owner authentication."""
    def __init__(self, config, simulation=False):
        self.config = config
        self.enabled = bool(config.get("enabled", True))
        self.simulation = simulation
        self.ready = False
        self.error = "not started"
        self.cv2 = None
        self.dictionary = None
        self.parameters = None

    def start(self):
        if not self.enabled:
            self.error = "disabled"
            return
        if self.simulation:
            self.ready = True
            self.error = ""
            return
        try:
            import cv2
            if not hasattr(cv2, "aruco"):
                raise RuntimeError("OpenCV was built without the aruco module")
            aruco = cv2.aruco
            dictionary_name = self.config.get("dictionary", "DICT_4X4_50")
            dictionary_id = getattr(aruco, dictionary_name, None)
            if dictionary_id is None:
                raise RuntimeError("unknown ArUco dictionary: %s" % dictionary_name)
            if hasattr(aruco, "getPredefinedDictionary"):
                self.dictionary = aruco.getPredefinedDictionary(dictionary_id)
            else:
                self.dictionary = aruco.Dictionary_get(dictionary_id)
            if hasattr(aruco, "DetectorParameters_create"):
                self.parameters = aruco.DetectorParameters_create()
            else:
                self.parameters = aruco.DetectorParameters()
            self.cv2 = cv2
            self.ready = True
            self.error = ""
        except Exception as exc:
            self.ready = False
            self.error = str(exc)
            LOG.warning("ArUco unavailable: %s", self.error)

    def detect(self, frame):
        """Return marker dictionaries containing id, corners, center and side size."""
        if not self.ready or self.simulation:
            return []
        aruco = self.cv2.aruco
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        if hasattr(aruco, "ArucoDetector"):
            detector = aruco.ArucoDetector(self.dictionary, self.parameters)
            corners, ids, unused = detector.detectMarkers(gray)
        else:
            corners, ids, unused = aruco.detectMarkers(
                gray, self.dictionary, parameters=self.parameters)
        if ids is None:
            return []
        markers = []
        for marker_id, marker_corners in zip(ids.reshape(-1), corners):
            points = np.asarray(marker_corners, dtype=np.float32).reshape(4, 2)
            sides = [float(np.linalg.norm(points[(index + 1) % 4] - points[index]))
                     for index in range(4)]
            markers.append({
                "id": int(marker_id),
                "corners": points,
                "center": tuple(np.mean(points, axis=0).tolist()),
                "side_px": float(np.mean(sides)),
            })
        return markers


def marker_belongs_to_person(marker, detection, margin_ratio=0.10):
    """Associate a marker with a person box using the marker center."""
    x1, y1, x2, y2 = detection.box
    width, height = max(1, x2 - x1), max(1, y2 - y1)
    margin_x, margin_y = width * margin_ratio, height * margin_ratio
    center_x, center_y = marker["center"]
    return (x1 - margin_x <= center_x <= x2 + margin_x and
            y1 - margin_y <= center_y <= y2 + margin_y)


def nearest_person_to_marker(marker, detections):
    """Return the person whose box is closest to the marker center.

    A marker inside a person box has zero box distance. Overlapping boxes are
    resolved using distance to the person-box center.
    """
    if not detections:
        return None
    marker_x, marker_y = marker["center"]

    def distance_key(detection):
        x1, y1, x2, y2 = detection.box
        dx = max(float(x1) - marker_x, 0.0, marker_x - float(x2))
        dy = max(float(y1) - marker_y, 0.0, marker_y - float(y2))
        box_distance_sq = dx * dx + dy * dy
        center_x, center_y = detection.center
        center_distance_sq = ((center_x - marker_x) ** 2 +
                              (center_y - marker_y) ** 2)
        return box_distance_sq, center_distance_sq

    return min(detections, key=distance_key)


def nearest_visual_person(detections):
    """Estimate the nearest person as the tallest visible person box."""
    if not detections:
        return None

    def proximity_key(detection):
        x1, y1, x2, y2 = detection.box
        height = max(0, y2 - y1)
        area = max(0, x2 - x1) * height
        return height, area, detection.confidence

    return max(detections, key=proximity_key)


COCO_KEYPOINTS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear",
                  "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                  "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
                  "right_knee", "left_ankle", "right_ankle")

TRT_POSE_KEYPOINTS = COCO_KEYPOINTS + ("neck",)
TRT_POSE_SKELETON = ([16, 14], [14, 12], [17, 15], [15, 13], [12, 13],
                     [6, 8], [7, 9], [8, 10], [9, 11], [2, 3], [1, 2],
                     [1, 3], [2, 4], [3, 5], [4, 6], [5, 7], [18, 1],
                     [18, 6], [18, 7], [18, 12], [18, 13])


class TrtPose(object):
    """Crop-level NVIDIA trt_pose adapter used only during owner authentication."""
    def __init__(self, config):
        self.config = config
        self.enabled = bool(config.get("enabled", False))
        self.ready = False
        self.error = "disabled"
        self.model = None
        self.torch = None
        self.device = config.get("device", "cuda:0")
        self.input_size = int(config.get("input_size", 224))

    def start(self):
        if not self.enabled:
            return
        try:
            import torch
            import trt_pose.models

            path = self.config.get("model")
            if not path or not os.path.isfile(path):
                raise RuntimeError("pose model missing: %s" % path)
            model = trt_pose.models.resnet18_baseline_att(
                len(TRT_POSE_KEYPOINTS), 2 * len(TRT_POSE_SKELETON))
            model.load_state_dict(torch.load(path, map_location="cpu"))
            self.model = model.to(self.device).eval()
            self.torch = torch
            self.ready = True
            self.error = ""
            LOG.info("trt_pose ready: %s", path)
        except Exception as exc:
            self.ready = False
            self.error = str(exc)
            self.model = None
            LOG.exception("trt_pose unavailable; dashboard remains active")

    def keypoints(self, frame, box):
        if not self.ready:
            return {}
        import cv2

        frame_height, frame_width = frame.shape[:2]
        x1, y1, x2, y2 = box
        width, height = max(1, x2 - x1), max(1, y2 - y1)
        padding_x = int(width * float(self.config.get("crop_padding_ratio", 0.15)))
        padding_y = int(height * float(self.config.get("crop_padding_ratio", 0.15)))
        crop_x1, crop_y1 = max(0, x1 - padding_x), max(0, y1 - padding_y)
        crop_x2, crop_y2 = min(frame_width, x2 + padding_x), min(frame_height, y2 + padding_y)
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        if crop.size == 0:
            return {}

        image = cv2.resize(crop, (self.input_size, self.input_size))[:, :, ::-1].copy()
        tensor = self.torch.from_numpy(image).permute(2, 0, 1).float().div(255.0)
        mean = self.torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = self.torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        tensor = tensor.sub(mean).div(std).unsqueeze(0).to(self.device)
        with self.torch.no_grad():
            cmap, unused_paf = self.model(tensor)
            heatmaps = cmap[0]
            scores, indices = self.torch.max(
                heatmaps.view(heatmaps.shape[0], -1), dim=1)

        # Authentication uses a tightly cropped, already selected person. A
        # per-joint heatmap maximum is sufficient and avoids the native
        # ParseObjects C++ extension that segfaults on this PyTorch 1.4 image.
        result = {}
        crop_width, crop_height = crop_x2 - crop_x1, crop_y2 - crop_y1
        map_height, map_width = int(heatmaps.shape[1]), int(heatmaps.shape[2])
        threshold = float(self.config.get("keypoint_threshold", 0.10))
        for part_index, name in enumerate(TRT_POSE_KEYPOINTS):
            confidence = float(scores[part_index])
            if confidence < threshold:
                continue
            flat_index = int(indices[part_index])
            peak_y, peak_x = divmod(flat_index, map_width)
            result[name] = (
                crop_x1 + ((peak_x + 0.5) / map_width) * crop_width,
                crop_y1 + ((peak_y + 0.5) / map_height) * crop_height,
                confidence)
        return result

    def close(self):
        self.model = None
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


class TorchScriptPose(object):
    """Optional crop-level pose adapter.

    The model must return 17x3 COCO keypoints normalized to its crop. This keeps
    the application independent of a specific pose training repository.
    """
    def __init__(self, config):
        self.config = config
        self.enabled = bool(config.get("enabled", False))
        self.model = None
        self.device = "cuda:0"
        self.ready = False
        self.error = "disabled"

    def start(self):
        if not self.enabled:
            return
        import torch
        path = self.config.get("model")
        if not path or not os.path.isfile(path):
            raise RuntimeError("pose model missing: %s" % path)
        self.model = torch.jit.load(path, map_location=self.device).eval()
        self.ready = True
        self.error = ""

    def keypoints(self, frame, box):
        if not self.enabled:
            return {}
        import cv2
        import torch
        x1, y1, x2, y2 = box
        crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if crop.size == 0:
            return {}
        image = cv2.resize(crop, (256, 256))[:, :, ::-1].copy()
        tensor = torch.from_numpy(image).permute(2, 0, 1).float().div(255.0).unsqueeze(0)
        with torch.no_grad():
            output = self.model(tensor.to(self.device))
        points = output[0].detach().cpu().numpy()
        result = {}
        for index, name in enumerate(COCO_KEYPOINTS):
            if points[index][2] >= 0.35:
                result[name] = (x1 + points[index][0] * (x2 - x1),
                                y1 + points[index][1] * (y2 - y1), points[index][2])
        return result

    def close(self):
        self.model = None


def create_pose(config):
    if config.get("backend", "trt_pose") == "torchscript":
        return TorchScriptPose(config)
    return TrtPose(config)
