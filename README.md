# Max

**An embodied AI agent that moves, pays, carries, and acts on your behalf.**

Max is a voice-controlled personal robot that turns a spoken request into a
completed real-world errand. It can find an item from a supported online
merchant, prepare the purchase, get its owner's approval, pay securely, travel
to the pickup point, and carry the item back.

## The idea

AI agents can reason, coordinate, and transact, but they remain trapped behind a
screen. They can decide what should happen in the real world, yet cannot go
there, act, or bring back the result.

Max gives the agent a body. A request no longer ends as an answer or a digital
transaction; it becomes a completed physical action.

## What Max does

- Understands errands through natural voice conversation
- Finds suitable products from supported merchants
- Prepares the order and asks for clarification when needed
- Makes owner-authorized payments through [Prava](https://www.prava.space/)
- Travels to the pickup point and securely carries the item back
- Reports progress through [Linq](https://linqapp.com/) and asks for help when
  necessary

## The experience

Tell Max what you need. Its agent finds the right option, prepares the purchase,
and presents the exact order for approval. After payment, Max travels to the
pickup point, collects the prepared package, and returns it to you.

## Why it is different

Max connects agentic commerce with the physical world. It does not stop after
placing an order, and it is not another public delivery platform. Max belongs to
one person and acts for that person—more like a capable robotic companion than a
courier.

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
