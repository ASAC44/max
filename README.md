# Max

**An embodied AI agent that moves, pays, carries, and acts on your behalf.**

Max is a voice-controlled personal robot that turns a spoken request into a
completed real-world errand. It can find an item, prepare the purchase, get its
owner's approval, pay securely, travel to the pickup point, and carry the item
back.

## The idea

AI agents can reason, coordinate, and transact, but they remain trapped behind a
screen. They can decide what should happen in the real world, yet cannot go
there, act, or bring back the result.

Max gives the agent a body. A request no longer ends as an answer or a digital
transaction; it becomes a completed physical action.

## What Max does

- Understands errands through natural voice conversation
- Finds suitable products and asks for missing details
- Prepares the exact order for its owner's approval
- Makes owner-authorized payments through [Prava](https://www.prava.space/)
- Travels to the pickup point and securely carries the item back
- Keeps the owner informed and asks for help when the real world gets messy

Max brings that loop together through OpenAI, Swiggy Instamart, Prava, Mission
Control, and its navigation stack. Payment attempts remain fail-closed: an
unknown result is never retried or presented as success.

## The intended experience

Tell Max what you need. Its agent finds the right option, prepares the purchase,
and presents the exact order for approval. After payment, Max travels to the
pickup point, collects the prepared package, and returns it to you.

## Why it is different

Max connects agentic commerce with the physical world. It does not stop after
placing an order, and it is not another public delivery platform. Max belongs to
one person and acts for that person—more like a capable robotic companion than a
courier.

Built for the [Agentic Commerce Hackathon](https://agentic-commerce.devfolio.co/overview).

## Engineering the agent

Max keeps language understanding separate from authority. OpenAI interprets the
owner's request, while a deterministic persisted workflow owns clarification,
quote approval, payment, checkout, and dispatch gates. The dashboard renders
that same state and continues the approved payment flow without exposing scoped
card credentials.

[Explore the agent API →](apps/api/README.md) · [Explore mission control →](apps/web/README.md)

## Engineering the body

Max's navigation prototype combines ROS 2, Gazebo, RTAB-Map visual SLAM,
AprilTag checkpoints, teach-and-repeat routing, and fail-closed obstruction
handling. It turns agent decisions into an observable pickup-and-return mission
without hiding safety stops or human intervention.

[Explore the navigation stack →](docs/mohit/NAVIGATION.md)

## Run it

First-time dependency setup:

```bash
./scripts/setup.sh
```

After configuring `.env`, Swiggy OAuth, and the dedicated checkout browser:

```bash
./scripts/dev.sh
```

[Read the complete setup, test, restart, and troubleshooting guide →](docs/RUN.md)

Scripts: [setup](scripts/setup.sh) · [start/stop development](scripts/dev.sh)

## Repository layout

```text
apps/
├── api/          # Max agent, mission workflow, persistence, integrations
│   ├── max_api/
│   ├── migrations/
│   └── tests/
├── web/          # Mission Control dashboard
│   └── src/
├── robot/        # navigation team's ROS 2 package, simulation, and tests
└── blinkit-mcp/  # retained unofficial experiment; not part of the Max flow
docs/             # shared project and operating documentation
scripts/          # dependency setup and local process launcher
```

The API consumes the robot interface delivered by the navigation team; it does
not duplicate robot or navigation logic.
