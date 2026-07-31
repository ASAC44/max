from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory("max_robot")
    database = LaunchConfiguration("database")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "database", default_value="/tmp/max_rtabmap.db"
            ),
            Node(
                package="rtabmap_slam",
                executable="rtabmap",
                name="rtabmap",
                parameters=[
                    os.path.join(share, "config", "rtabmap_mapping.yaml"),
                    {"database_path": database},
                ],
                remappings=[
                    ("rgb/image", "/camera/image_rect"),
                    ("rgb/camera_info", "/camera/camera_info"),
                    ("odom", "/wheel/odom"),
                ],
                output="screen",
            ),
            Node(
                package="apriltag_ros",
                executable="apriltag_node",
                name="apriltag",
                parameters=[os.path.join(share, "config", "tags.yaml")],
                remappings=[
                    ("image_rect", "/camera/image_rect"),
                    ("camera_info", "/camera/camera_info"),
                    ("detections", "/apriltag/detections"),
                ],
            ),
        ]
    )
