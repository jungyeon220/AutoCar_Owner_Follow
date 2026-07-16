import math
import numpy as np


def cosine_similarity(a, b):
    if a is None or b is None:
        return 0.0
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denom <= 1e-9 else max(0.0, min(1.0, float(np.dot(a, b) / denom)))


class AppearanceEncoder(object):
    """Brightness-tolerant spatial HSV clothing-pattern descriptor."""
    def _clothing_crop(self, frame, box):
        x1, y1, x2, y2 = box
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        left = max(0, int(x1 + width * 0.10))
        right = max(left, int(x1 + width * 0.90))
        top = max(0, int(y1 + height * 0.18))
        bottom = max(top, int(y1 + height * 0.68))
        return frame[top:bottom, left:right]

    def _pattern(self, crop):
        import cv2
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        features = []
        height, width = hsv.shape[:2]
        for row in range(2):
            for column in range(3):
                y1, y2 = height * row // 2, height * (row + 1) // 2
                x1, x2 = width * column // 3, width * (column + 1) // 3
                cell = hsv[y1:y2, x1:x2]
                if cell.size == 0:
                    features.extend([0.0] * 97)
                    continue
                hist = cv2.calcHist([cell], [0, 1], None,
                                    [12, 8], [0, 180, 0, 256])
                cv2.normalize(hist, hist)
                features.extend(hist.reshape(-1).tolist())
                features.append(float(np.mean(cell[:, :, 2])) / 255.0)
        return np.asarray(features, dtype=np.float32)

    def encode(self, frame, box):
        return self._pattern(self._clothing_crop(frame, box))

    def brightness_variants(self, frame, box):
        """Create bounded expected clothing patterns for changing illumination."""
        crop = self._clothing_crop(frame, box)
        if crop.size == 0:
            return []
        variants = []
        for factor in (0.60, 0.80, 1.00, 1.20, 1.40):
            adjusted = np.clip(crop.astype(np.float32) * factor, 0, 255).astype(np.uint8)
            feature = self._pattern(adjusted)
            if feature is not None:
                variants.append((factor, feature))
        return variants


class OwnerProfile(object):
    def __init__(self):
        self.track_id = None
        self.feature = None
        self.registered_distance = None
        self.samples = []
        self.variant_samples = {}
        self.brightness_features = {}
        self.cds_samples = []
        self.registered_cds = None

    def begin(self, track_id):
        self.track_id = track_id
        self.feature = None
        self.samples = []
        self.variant_samples = {}
        self.brightness_features = {}
        self.cds_samples = []
        self.registered_cds = None

    def add_sample(self, feature, brightness_variants=None, cds_value=None):
        if feature is not None:
            self.samples.append(np.asarray(feature, dtype=np.float32))
        for factor, variant in brightness_variants or []:
            self.variant_samples.setdefault(float(factor), []).append(
                np.asarray(variant, dtype=np.float32))
        if cds_value is not None:
            self.cds_samples.append(float(cds_value))

    def finalize(self, distance=None):
        if not self.samples:
            return False
        self.feature = np.mean(np.stack(self.samples), axis=0)
        self.registered_distance = distance
        self.brightness_features = {
            factor: np.mean(np.stack(samples), axis=0)
            for factor, samples in self.variant_samples.items() if samples
        }
        if self.cds_samples:
            self.registered_cds = float(np.median(np.asarray(self.cds_samples)))
        self.samples = []
        self.variant_samples = {}
        self.cds_samples = []
        return True

    def _appearance(self, feature, cds_value=None):
        candidates = [self.feature]
        if self.brightness_features:
            factors = list(self.brightness_features)
            if (cds_value is not None and self.registered_cds is not None and
                    cds_value > 0 and self.registered_cds > 0):
                ratio = max(0.50, min(1.50, float(cds_value) / self.registered_cds))
                inverse = max(0.50, min(1.50, self.registered_cds / float(cds_value)))
                selected = sorted(factors,
                                  key=lambda value: min(abs(value - ratio),
                                                        abs(value - inverse)))[:2]
                candidates.extend(self.brightness_features[value] for value in selected)
            else:
                candidates.extend(self.brightness_features.values())
        return max([cosine_similarity(candidate, feature) for candidate in candidates] or [0.0])

    def score(self, detection, previous_track_id, cds_value=None):
        appearance = self._appearance(detection.feature, cds_value)
        tracking = 1.0 if detection.track_id == previous_track_id else appearance * 0.6
        clothing = appearance
        body = 1.0
        return (0.40 * tracking + 0.35 * appearance +
                0.20 * clothing + 0.05 * body)


def classify_candidates(scored, confirm_score=0.70, ambiguity_margin=0.12):
    if not scored:
        return "uncertain", None
    ranked = sorted(scored, key=lambda item: item[0], reverse=True)
    best_score, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_score < confirm_score:
        return "uncertain", None
    if best_score - second_score < ambiguity_margin:
        return "ambiguous", None
    return "confirmed", best
