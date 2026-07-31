from glob import glob

from setuptools import find_packages, setup


setup(
    name="max_robot",
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/max_robot"]),
        ("share/max_robot", ["package.xml"]),
        ("share/max_robot/config", glob("config/*")),
        ("share/max_robot/launch", glob("launch/*")),
        ("share/max_robot/models/max_robot", glob("models/max_robot/*")),
        ("share/max_robot/references", glob("references/*")),
        ("share/max_robot/worlds", glob("worlds/*")),
    ],
    install_requires=["setuptools", "numpy", "stripe>=15.3.1,<16"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "max-control = max_robot.ros_node:main",
            "max-obstruction = max_robot.vision_node:main",
            "max-odom-tf = max_robot.odom_tf_node:main",
            "max-record-reference = max_robot.vision_node:record_reference",
            "max-web = max_robot.cli:main",
        ]
    },
)
