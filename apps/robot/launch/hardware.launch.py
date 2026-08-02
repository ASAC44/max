import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory("max_robot")
    motor_config = LaunchConfiguration("motor_config")
    return LaunchDescription([
        DeclareLaunchArgument("database", default_value="/tmp/max_rtabmap.db"),
        DeclareLaunchArgument("reference_dir", default_value=os.path.join(share, "references")),
        DeclareLaunchArgument("motor_config", default_value=os.path.join(share, "config", "max.yaml")),
        Node(
            package="camera_ros",
            executable="camera_node",
            name="camera",
            parameters=[{
                "camera": 0,
                "role": "video",
                "width": 640,
                "height": 480,
                "frame_id": "camera_link",
                "FrameDurationLimits": [50000, 50000],
            }],
            remappings=[
                ("image_raw", "/camera/image_raw"),
                ("camera_info", "/camera/camera_info"),
            ],
            output="screen",
        ),
        Node(
            package="image_proc",
            executable="rectify_node",
            name="camera_rectify",
            remappings=[
                ("image", "/camera/image_raw"),
                ("camera_info", "/camera/camera_info"),
                ("image_rect", "/camera/image_rect"),
            ],
            output="screen",
        ),
        Node(package="max_robot", executable="max-odom-tf"),
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            arguments=[
                "--x", "0.19", "--y", "0", "--z", "0.12",
                "--roll", "0", "--pitch", "0", "--yaw", "0",
                "--frame-id", "base_link", "--child-frame-id", "camera_link",
            ],
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(share, "launch", "navigation.launch.py")),
            launch_arguments={
                "database": LaunchConfiguration("database"),
                "reference_dir": LaunchConfiguration("reference_dir"),
            }.items(),
        ),
        Node(
            package="max_robot",
            executable="max-motors",
            parameters=[motor_config],
            output="screen",
        ),
    ])
