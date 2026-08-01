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

## Engineering the agent

Max keeps language understanding separate from authority. Its typed OpenAI
interpretation path is configured but still pending live-model validation; a
deterministic, persisted mission workflow owns approval, payment, checkout, and
dispatch gates. The operator dashboard renders that same event history instead
of inventing a second version of mission state.

[Explore the agent API →](apps/api/README.md) · [Explore mission control →](apps/web/README.md)

## Engineering the body

Max's navigation prototype combines ROS 2, Gazebo, RTAB-Map visual SLAM,
AprilTag checkpoints, teach-and-repeat routing, and fail-closed obstruction
handling. It turns agent decisions into an observable pickup-and-return mission
without hiding safety stops or human intervention.

[Explore the navigation stack →](docs/AI_NAVIGATION_PLAN.md)

## Repository layout

```text
apps/
├── api/    # Max agent, mission workflow, persistence, integrations
│   ├── max_api/
│   ├── migrations/
│   └── tests/
├── web/    # admin dashboard
│   └── src/
└── robot/  # navigation team's ROS 2 package, simulation, and tests
docs/       # shared project documentation
```

The API consumes the robot interface delivered by the navigation team; it does
not duplicate robot or navigation logic.

## Stripe test checkout

The local Max web server can create authenticated, per-order Stripe-hosted
Checkout URLs and record signed payment webhooks. It accepts Stripe test keys
only and never handles card credentials. See the
[Stripe payment demo](docs/STRIPE_PAYMENT_DEMO.md) for setup and the REST
contract.
