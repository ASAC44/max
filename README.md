# Max

**An embodied AI agent that moves, pays, carries, and acts on your behalf.**

Max is a voice-controlled robot that handles real-world tasks on its owner's behalf. It can understand a request, travel to where the task needs to happen, carry items, make an authorized payment, and return with the result.

## The idea

AI assistants can search, plan, and pay online, but they stop at the edge of the screen. Physical errands still require a person to leave what they are
doing, travel somewhere, wait, pay, and carry something back.

Max gives the personal agent a physical presence. You tell it what you need; it works out the task and goes.

## What Max does

- Accepts errands through natural voice conversation
- Plans and carries out physical missions
- Navigates to real-world destinations
- Collects and securely carries items
- Makes owner-authorized payments through [Prava](https://www.prava.space/)
- Reports progress through [Linq](https://linqapp.com/) and asks for help when
  necessary

## Why it is different

Max is not another delivery platform. It belongs to one person and acts for that person; more like a capable robotic companion than a public courier.

Built for the [Agentic Commerce Hackathon](https://agentic-commerce.devfolio.co/overview).

## Phase 1: navigation without hardware

The repository now contains a ROS 2/Gazebo implementation for developing the
first indoor pickup-and-return route before the robot hardware arrives:

- RTAB-Map visual SLAM with wheel odometry
- AprilTag checkpoints
- camera-only obstruction stopping
- teach-and-repeat route following
- local web controls and a fail-closed safety gate

The current Raspberry Pi 5, Camera Module 3, and BTS7960 hardware has no wheel
encoders. Simulation works with virtual wheel odometry, but autonomous movement
on the physical robot remains disabled until a measured odometry source is
added. The BTS7960 is a motor driver, not an odometry sensor.

Run the dependency-free core checks:

```bash
python3 -m unittest discover -s tests -v
```

See [the hardware-free navigation plan](docs/AI_NAVIGATION_PLAN.md) for the
ROS/Gazebo setup, test workflow, limits, and hardware-arrival checklist.
