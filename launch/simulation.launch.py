from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory("max_robot")
    ros_gz_share = get_package_share_directory("ros_gz_sim")
    world = os.path.join(share, "worlds", "max_indoor.sdf")
    return LaunchDescription(
        [
            SetEnvironmentVariable(
                "GZ_SIM_RESOURCE_PATH", os.path.join(share, "models")
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(ros_gz_share, "launch", "gz_sim.launch.py")
                ),
                launch_arguments={"gz_args": f"-r {world}"}.items(),
            ),
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                parameters=[
                    {"config_file": os.path.join(share, "config", "gz_bridge.yaml")}
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
        ]
    )
