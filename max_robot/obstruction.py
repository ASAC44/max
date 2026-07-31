from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .core import ObstructionState


@dataclass(frozen=True)
class ObstructionConfig:
    difference_ratio: float = 0.08
    ttc_seconds: float = 1.5
    minimum_tracks: int = 30
    confirmation_frames: int = 3
    clear_seconds: float = 5.0


@dataclass(frozen=True)
class VisionMeasurement:
    difference_ratio: float
    ttc_seconds: float | None
    track_count: int | None
    alignment_ok: bool


class ObstructionMonitor:
    def __init__(self, config: ObstructionConfig | None = None) -> None:
        self.config = config or ObstructionConfig()
        self.state = ObstructionState.CLEAR
        self.reason = ""
        self._blocked_frames = 0
        self._clear_since: float | None = None

    def update(
        self, measurement: VisionMeasurement, now: float | None = None
    ) -> ObstructionState:
        now = time.monotonic() if now is None else now
        blocked_reason = self._blocked_reason(measurement)

        if blocked_reason:
            self._clear_since = None
            self._blocked_frames += 1
            self.reason = blocked_reason
            if self._blocked_frames >= self.config.confirmation_frames:
                self.state = ObstructionState.STOPPED
            else:
                self.state = ObstructionState.SUSPECTED
            return self.state

        self._blocked_frames = 0
        if self.state in {ObstructionState.SUSPECTED, ObstructionState.CLEAR}:
            self.state = ObstructionState.CLEAR
            self.reason = ""
            return self.state

        if self._clear_since is None:
            self._clear_since = now
        self.state = ObstructionState.WAITING_FOR_CLEAR
        self.reason = "clear interval and operator resume required"
        if now - self._clear_since >= self.config.clear_seconds:
            self.state = ObstructionState.CLEAR
            self.reason = ""
            self._clear_since = None
        return self.state

    def force_stop(self, reason: str) -> None:
        self.state = ObstructionState.STOPPED
        self.reason = reason
        self._blocked_frames = self.config.confirmation_frames
        self._clear_since = None

    def _blocked_reason(self, measurement: VisionMeasurement) -> str:
        if not measurement.alignment_ok:
            return "reference alignment failed"
        if (
            measurement.track_count is not None
            and measurement.track_count < self.config.minimum_tracks
        ):
            return "insufficient visual tracks"
        if measurement.difference_ratio >= self.config.difference_ratio:
            return "route image changed"
        if (
            measurement.ttc_seconds is not None
            and measurement.ttc_seconds <= self.config.ttc_seconds
        ):
            return "time to collision below threshold"
        return ""


class OpenCVObstructionDetector:
    """OpenCV frontend; the state logic above stays testable without OpenCV."""

    def __init__(self, path_polygon: np.ndarray | None = None) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for camera obstruction detection") from exc
        self.cv2 = cv2
        self.orb = cv2.ORB_create(nfeatures=800)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.path_polygon = path_polygon

    def compare_reference(
        self, reference: np.ndarray, current: np.ndarray
    ) -> tuple[float, bool]:
        cv2 = self.cv2
        reference_gray = self._gray(reference)
        current_gray = self._gray(current)
        ref_points, ref_desc = self.orb.detectAndCompute(reference_gray, None)
        cur_points, cur_desc = self.orb.detectAndCompute(current_gray, None)
        if ref_desc is None or cur_desc is None:
            return 1.0, False

        matches = sorted(
            self.matcher.match(ref_desc, cur_desc), key=lambda match: match.distance
        )
        if len(matches) < 12:
            return 1.0, False
        source = np.float32([ref_points[m.queryIdx].pt for m in matches[:100]])
        target = np.float32([cur_points[m.trainIdx].pt for m in matches[:100]])
        transform, inliers = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
        if transform is None or inliers is None or int(inliers.sum()) < 8:
            return 1.0, False

        aligned = cv2.warpPerspective(
            reference_gray, transform, (current_gray.shape[1], current_gray.shape[0])
        )
        difference = cv2.absdiff(aligned, current_gray)
        difference = cv2.threshold(difference, 35, 255, cv2.THRESH_BINARY)[1]
        kernel = np.ones((3, 3), np.uint8)
        difference = cv2.morphologyEx(difference, cv2.MORPH_OPEN, kernel)
        mask = self._path_mask(current_gray.shape)
        changed = cv2.countNonZero(cv2.bitwise_and(difference, mask))
        return changed / max(1, cv2.countNonZero(mask)), True

    def estimate_ttc(
        self,
        previous: np.ndarray,
        current: np.ndarray,
        dt_seconds: float,
        *,
        angular_velocity: float = 0.0,
        horizontal_fov: float = 1.15,
    ) -> tuple[float | None, int]:
        if dt_seconds <= 0:
            raise ValueError("dt_seconds must be positive")
        cv2 = self.cv2
        previous_gray = self._gray(previous)
        current_gray = self._gray(current)
        mask = self._path_mask(previous_gray.shape)
        points = cv2.goodFeaturesToTrack(
            previous_gray,
            maxCorners=300,
            qualityLevel=0.01,
            minDistance=7,
            mask=mask,
        )
        if points is None:
            return None, 0
        tracked, status, _ = cv2.calcOpticalFlowPyrLK(
            previous_gray, current_gray, points, None
        )
        if tracked is None or status is None:
            return None, 0
        old = points[status.ravel() == 1].reshape(-1, 2)
        new = tracked[status.ravel() == 1].reshape(-1, 2)
        if len(old) < 2:
            return None, len(old)

        # Remove the dominant horizontal flow caused by the robot yawing.
        new[:, 0] += (
            angular_velocity * dt_seconds * previous_gray.shape[1] / horizontal_fov
        )
        center = np.array([previous_gray.shape[1] / 2, previous_gray.shape[0] / 2])
        old_radius = np.linalg.norm(old - center, axis=1)
        new_radius = np.linalg.norm(new - center, axis=1)
        valid = old_radius > 8
        expansion = (new_radius[valid] - old_radius[valid]) / old_radius[valid]
        expansion = expansion[expansion > 0.002]
        if len(expansion) == 0:
            return None, len(old)
        ttc = dt_seconds / float(np.median(expansion))
        return ttc, len(old)

    def _gray(self, image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return image
        return self.cv2.cvtColor(image, self.cv2.COLOR_BGR2GRAY)

    def _path_mask(self, shape: tuple[int, ...]) -> np.ndarray:
        height, width = shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)
        polygon = self.path_polygon
        if polygon is None:
            polygon = np.array(
                [
                    [int(width * 0.15), height - 1],
                    [int(width * 0.4), int(height * 0.45)],
                    [int(width * 0.6), int(height * 0.45)],
                    [int(width * 0.85), height - 1],
                ],
                dtype=np.int32,
            )
        self.cv2.fillPoly(mask, [polygon], 255)
        return mask
