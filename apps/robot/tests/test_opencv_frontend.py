import unittest

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from max_robot.obstruction import OpenCVObstructionDetector


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class OpenCVFrontendTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(7)
        self.reference = rng.integers(0, 256, (480, 640), dtype=np.uint8)
        self.detector = OpenCVObstructionDetector()

    def test_identical_reference_aligns_and_is_clear(self) -> None:
        difference, aligned = self.detector.compare_reference(
            self.reference, self.reference.copy()
        )
        self.assertTrue(aligned)
        self.assertLess(difference, 0.001)

    def test_changed_path_region_is_measurable(self) -> None:
        changed = self.reference.copy()
        changed[300:440, 260:380] = 0
        difference, aligned = self.detector.compare_reference(
            self.reference, changed
        )
        self.assertTrue(aligned)
        self.assertGreater(difference, 0.02)

    def test_expanding_features_produce_ttc(self) -> None:
        previous = np.zeros((480, 640), dtype=np.uint8)
        for x in range(180, 461, 28):
            for y in range(230, 431, 25):
                cv2.circle(previous, (x, y), 2, 255, -1)
        transform = cv2.getRotationMatrix2D((320, 240), 0, 1.05)
        current = cv2.warpAffine(previous, transform, (640, 480))
        ttc, tracks = self.detector.estimate_ttc(previous, current, 0.1)
        self.assertGreaterEqual(tracks, 30)
        self.assertIsNotNone(ttc)
        self.assertLess(ttc, 3.0)


if __name__ == "__main__":
    unittest.main()
