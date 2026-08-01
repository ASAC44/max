# Product and Scope

> Status: approved product scope. Swiggy Instamart MCP plus browser checkout is
> the active commerce candidate; the combined path remains subject to Phase 1.

## Product vision

Max is a personal embodied AI agent. It receives an owner's request, handles the
digital work needed to prepare an authorized purchase, travels through the
physical world, collects the prepared item, and returns with the result.

Max is not a public delivery service. It belongs to one owner and acts within
that owner's permissions.

## Core product promise

```text
owner expresses intent
→ Max understands and clarifies it
→ Max finds a supported way to fulfil it
→ owner reviews and authorizes the exact purchase
→ Max completes the supported digital transaction flow
→ Max performs the physical pickup mission
→ owner receives the item and a truthful final status
```

The important product idea is not merely “delivery after checkout.” Max gives an
AI agent physical agency: the ability to turn a digital decision into a
completed action in the real world.

## Users and actors

- **Owner:** the one person Max serves and the only person authorized to approve
  purchases and missions.
- **Max agent:** understands the request, uses allowed tools, maintains the
  workflow, and explains status.
- **Swiggy commerce path:** the official Instamart MCP supplies authenticated
  discovery, cart, quote, and read-only order behavior; the normal Swiggy
  browser supplies card entry if Phase 1 proves the cart handoff. Max uses only
  behavior reproduced during Phase 1.
- **Prava:** handles user-approved scoped card-payment permission and payment
  session state.
- **Robot/navigation system:** travels to a known destination and returns.
- **Pickup person or point:** provides the already prepared package.
- **Notification provider:** sends progress and assistance requests through Linq
  or the tested fallback.
- **Operator/admin:** observes the demo, diagnoses failures, and performs only
  explicitly permitted recovery actions.

## Intended user experience

1. The owner speaks a request such as “get milk under ₹300.”
2. Max extracts the item, constraints, destination, and budget meaning.
3. If a required fact is missing or ambiguous, Max asks a focused question.
4. Max searches the live Swiggy Instamart catalog through its official MCP.
5. Max selects or presents an option according to the approved selection rule.
6. Max obtains the final merchant quote, including delivery, taxes, and fees.
7. The owner sees the exact merchant, item, quantity, total, and pickup plan.
8. The owner authorizes the purchase through Prava's tested flow.
9. The merchant checkout returns a truthful success or failure result.
10. When the mission is permitted to continue, Max travels to the fixed pickup
    point, obtains the prepared package, secures it, and returns.
11. Max reports completion, cancellation, or the exact help required.

Voice is the intended owner experience. A text input harness may be used while
building the core agent, but it is a development surface rather than the final
product interaction.

## Hackathon MVP boundary

The smallest credible demonstration should contain:

- one owner;
- one Max robot;
- one active errand at a time;
- Swiggy Instamart MCP plus the matching Swiggy browser cart as one commerce
  path;
- one product or simple single-merchant cart;
- explicit handling of maximum, exact, and range budgets when used;
- one Prava sandbox payment flow with passkey approval;
- a real merchant checkout attempt using the issued sandbox credential, with the
  expected result reported back to Prava;
- one fixed, tested pickup destination;
- one package placed or prepared according to the truthful demo scenario;
- robot travel to pickup and return;
- one primary notification route, preferably Linq if it proves reliable;
- Telegram as a fallback only after its role is explicitly decided;
- an admin dashboard showing authoritative workflow state; and
- safe cancellation, timeout, and human-help behavior.

Swiggy is the active candidate, but its MCP-to-browser cart continuity, card
form, exact Prava surface, and supported demo transaction claim remain open until
manual testing. The story must not claim a working Swiggy checkout before the
payment/merchant gate passes.

## Product behavior rules

### Request and clarification

- Never invent a missing product, merchant, quantity, budget, or destination.
- Preserve whether a budget means exact, maximum, minimum, or a range.
- Ask only for information required to continue safely.
- A changed owner instruction creates a new reviewed plan; it does not silently
  mutate an approved purchase.

### Product selection

- Use only merchant data returned by the verified commerce source.
- Explain the selection using the owner's stated constraints.
- Do not substitute an unavailable item without new owner approval.
- If no valid option exists, stop or ask the owner to change the request.
- Recheck availability and final price before requesting payment approval.

### Approval and payment

- Present merchant, item, variant, quantity, full total, currency, and important
  fulfilment details before approval.
- Use Prava's hard approval and amount/merchant controls; do not rely only on an
  LLM confirmation message.
- Never widen the approved amount or merchant automatically.
- Never call a Prava session an order.
- Never call a merchant checkout attempt successful without merchant evidence.
- Unknown payment outcomes require status inspection, not blind retry.

### Mission dispatch

- Product-vision behavior: dispatch only after a real Swiggy order is confirmed
  and the agreed delivery handoff point reports that pickup is valid.
- Hackathon sandbox behavior: the merchant attempt is expected to decline. A
  physical package may be staged for the robot demonstration only if the team
  clearly labels the digital transaction and physical fulfilment as separate
  sandbox/demo events.
- Never imply that Swiggy, Instamart, or a rider prepared or released an order
  after a failed payment. Swiggy commerce is production-facing; the
  sandbox-decline demo creates no
  fulfilment claim.
- For the staged physical demo, a point of contact confirms a separately prepared
  package at the fixed handoff point. The dashboard records this as staged, not
  as a Swiggy event.
- The dashboard may offer **Run staged fulfilment** after the decline. It creates
  a separate staged branch whose premise is “simulated successful payment/order”
  so judges can see the downstream handoff, pickup, and return. It never edits
  the recorded Swiggy or Prava result.
- The mission controller, not free-form LLM text, decides whether dispatch is
  permitted.

### Pickup and return

- The current target is a known pickup point, not arbitrary shelf navigation.
- The robot does not need product recognition inside a shop for this MVP.
- The robot must know whether the package was secured before returning.
- If pickup cannot be confirmed, request help or return according to the tested
  recovery policy; do not silently claim success.

### Notifications

- Notify only on meaningful transitions: approval required, dispatched,
  arrived, pickup problem, returning, completed, cancelled, or failed.
- A notification provider is not the source of truth. Mission state lives in the
  backend/state store.
- If Linq is unavailable, the fallback must preserve the same event meaning and
  must be tested end to end.

## Product vision versus demo evidence

| Product claim | Minimum evidence needed in the demo |
| --- | --- |
| Understands a request | Request becomes a correct structured intent; ambiguity triggers clarification |
| Finds a product | Result comes from the live Swiggy Instamart MCP catalog |
| Prepares a purchase | Exact cart/quote is visible and reproducible |
| Owner authorizes payment | Prava approval/passkey event is observed |
| Attempts checkout | Scoped credential reaches the merchant checkout and returns a result |
| Places an order | Merchant returns a real order confirmation or sandbox order ID |
| Travels autonomously | Navigation team demonstrates the defined route without hidden teleoperation |
| Collects an item | Pickup/cargo event is observed and the item is physically carried |
| Reports status | Linq/Telegram receives the expected event and dashboard state agrees |
| Works end to end | One correlated mission ID links every demonstrated stage without manual state editing |

If the evidence only proves a sandbox checkout decline and a separately staged
physical pickup, describe exactly that. Do not market it as a real merchant
order.

## Explicit non-goals for this MVP

- Paying merchant UPI QRs.
- Paying a classmate, delivery rider, or arbitrary person.
- Card-to-UPI conversion, cash, bank transfer, or P2P transfer.
- Bargaining or price negotiation.
- Unapproved substitutions.
- Shelf navigation or visual product recognition in a shop.
- Arbitrary destinations across an untested campus.
- Multiple owners, shared public use, or delivery marketplace behavior.
- Multi-merchant carts or split payments.
- Recurring Prava mandates.
- Production charges merely to make the demo appear more real.
- General web automation across unsupported merchants.
- Hiding failed stages behind mocks while claiming they are integrated.

## Completion criteria

The software owner's work is complete for the hackathon when:

1. The current scope and demo claim are reviewed and accepted.
2. The chosen Prava/merchant flow is manually reproduced and documented.
3. The main agent drives the verified workflow rather than a scripted sequence
   falsely presented as agent behavior.
4. The admin dashboard displays the authoritative request, commerce, payment,
   mission, robot, and notification states needed for the demo.
5. Voice input works in the actual demo environment and safely confirms
   purchase-critical information.
6. Linq works end to end, or the explicitly selected Telegram fallback does.
7. The navigation/hardware boundary is integrated using a tested contract.
8. One complete demo run and the important failure paths pass with recorded
   evidence.
9. The public README, private docs, dashboard, and spoken demo tell the same
   truthful story.
