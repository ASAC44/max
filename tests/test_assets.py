import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AssetTests(unittest.TestCase):
    def test_xml_assets_are_well_formed(self) -> None:
        for relative in [
            "package.xml",
            "models/max_robot/model.config",
            "models/max_robot/model.sdf",
            "worlds/max_indoor.sdf",
        ]:
            with self.subTest(relative):
                ET.parse(ROOT / relative)

    def test_route_matches_simulated_endpoints(self) -> None:
        route = json.loads((ROOT / "config/route.json").read_text())
        self.assertEqual(route["waypoints"][0], {"x": 0.0, "y": 0.0})
        self.assertEqual(route["waypoints"][-1], {"x": 2.0, "y": 2.0})
        self.assertEqual((route["home_tag"], route["pickup_tag"]), (0, 2))

    def test_apriltag_textures_are_ten_by_ten(self) -> None:
        for tag_id in range(3):
            path = ROOT / f"models/max_robot/tag36h11_{tag_id}.pgm"
            tokens = [
                token
                for line in path.read_text().splitlines()
                if not line.startswith("#")
                for token in line.split()
            ]
            self.assertEqual(tokens[:4], ["P2", "10", "10", "255"])
            self.assertEqual(len(tokens[4:]), 100)


if __name__ == "__main__":
    unittest.main()
