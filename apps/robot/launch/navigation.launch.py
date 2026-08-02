from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory("max_robot")
    database = LaunchConfiguration("database")
    reference_dir = LaunchConfiguration("reference_dir")
    runtime_mode = LaunchConfiguration("runtime_mode")
    route = LaunchConfiguration("route")
    control_config = LaunchConfiguration("control_config")
    tag_config = LaunchConfiguration("tag_config")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "database", default_value="/tmp/max_rtabmap.db"
            ),
            DeclareLaunchArgument(
                "reference_dir",
                default_value=os.path.join(share, "references"),
            ),
            DeclareLaunchArgument("runtime_mode", default_value="simulation"),
            DeclareLaunchArgument(
                "route",
                default_value=os.path.join(share, "config", "route.json"),
            ),
            DeclareLaunchArgument(
                "control_config",
                default_value=os.path.join(share, "config", "max.yaml"),
            ),
            DeclareLaunchArgument(
                "tag_config",
                default_value=os.path.join(share, "config", "tags.yaml"),
            ),
            Node(
                package="rtabmap_slam",
                executable="rtabmap",
                name="rtabmap",
                parameters=[
                    os.path.join(share, "config", "rtabmap_localization.yaml"),
                    {"database_path": database},
                ],
                remappings=[
                    ("rgb/image", "/camera/image_rect"),
                    ("rgb/camera_info", "/camera/camera_info"),
                    ("odom", "/wheel/odom"),
                    ("localization_pose", "/localization/pose"),
                ],
                output="screen",
            ),
            Node(
                package="apriltag_ros",
                executable="apriltag_node",
                name="apriltag",
                parameters=[tag_config],
                remappings=[
                    ("image_rect", "/camera/image_rect"),
                    ("camera_info", "/camera/camera_info"),
                    ("detections", "/apriltag/detections"),
                ],
            ),
            Node(
                package="max_robot",
                executable="max-obstruction",
                parameters=[
                    os.path.join(share, "config", "max.yaml"),
                    {"reference_dir": reference_dir},
                ],
                output="screen",
            ),
            Node(
                package="max_robot",
                executable="max-control",
                parameters=[
                    control_config,
                    {"route_file": route, "runtime_mode": runtime_mode},
                ],
                output="screen",
            ),
        ]
    )
