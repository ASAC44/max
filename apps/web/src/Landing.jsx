import { useRef, useState } from "react";

export const Arrow = () => (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d="M4 10h11M11 5l5 5-5 5" />
  </svg>
);

export function PublicNav() {
  return (
    <nav className="site-nav" aria-label="Primary navigation">
      <a className="wordmark" href="/" aria-label="Max home">max<span>.</span></a>
      <div className="nav-links">
        <a href="/">Overview</a>
        <a href="/live">Live</a>
        <a href="/history">History</a>
        <a href="/ondc">ONDC sandbox</a>
      </div>
      <a className="operator-link" href="/control">
        Operator access <Arrow />
      </a>
    </nav>
  );
}

const stages = [
  {
    number: "01",
    title: "Ask",
    copy: "“Bring me a cold mango juice under ₹150.”",
  },
  {
    number: "02",
    title: "Approve",
    copy: "Max pins the Swiggy quote. You approve that exact amount in Prava.",
  },
  {
    number: "03",
    title: "Follow",
    copy: "The order and every delivery update stay attached to the same mission.",
  },
  {
    number: "04",
    title: "Bring back",
    copy: "At the handoff, Max sends the robot to collect the package and return.",
  },
];

const journey = [
  {
    kind: "request",
    label: "Telegram",
    title: "Start with a normal message.",
    copy: "Ask on Telegram and include the item, budget and campus destination.",
  },
  {
    kind: "cart",
    label: "Max shops",
    title: "Search more than one marketplace.",
    copy: "Max checks Swiggy Instamart and ONDC before choosing an item.",
  },
  {
    kind: "approval",
    label: "You approve",
    title: "Approve one exact payment.",
    copy: "The order pauses until you approve the amount through Prava.",
  },
  {
    kind: "delivery",
    label: "Max follows",
    title: "Follow the order to campus.",
    copy: "Commerce, checkout and delivery updates stay on the same mission.",
  },
  {
    kind: "return",
    label: "Max brings it",
    title: "Bring it from the gate to you.",
    copy: "The robot meets the delivery and completes the trip across campus.",
  },
];

function JourneyVisual({ kind }) {
  if (kind === "request") return (
    <div className="telegram-window">
      <header><i>T</i><div><strong>Max</strong><span>Telegram</span></div><time>now</time></header>
      <div className="telegram-chat">
        <p className="owner-message">Bring me a cold mango juice under ₹150 to the library.</p>
        <p className="agent-message"><i />Got it. I’m checking the available marketplaces.</p>
      </div>
    </div>
  );
  if (kind === "cart") return (
    <div className="marketplace-window">
      <header><i /><i /><i /><span>Marketplace search</span></header>
      <div className="marketplace-search">cold mango juice <b>⌕</b></div>
      <div className="marketplace-tabs"><span className="active">All</span><span>Swiggy Instamart</span><span>ONDC</span></div>
      <div className="marketplace-result selected"><i>B</i><div><strong>B Natural Mango Juice</strong><span>1 litre · 10 min</span></div><b>₹110</b><em>Best match</em></div>
      <div className="marketplace-result"><i>M</i><div><strong>Mango fruit drink</strong><span>1 litre · ONDC seller</span></div><b>₹125</b></div>
    </div>
  );
  if (kind === "approval") return (
    <div className="approval-window">
      <header><span>Prava</span><small>Secure approval</small></header>
      <div className="approval-order"><div><small>Order</small><strong>B Natural Mango Juice</strong></div><span>₹110</span></div>
      <div className="approval-total"><small>Exact amount</small><strong>₹110.00</strong><span>INR</span></div>
      <div className="approval-confirmed"><i>✓</i><span><strong>Approved by owner</strong><small>Max can continue with this amount only.</small></span></div>
    </div>
  );
  if (kind === "delivery") return (
    <div className="tracking-window">
      <header><span>Swiggy Instamart</span><small>Order 4F21</small></header>
      <div className="tracking-status"><i /><div><small>Current update</small><strong>Arriving at the campus gate</strong></div><span>6 min</span></div>
      <div className="tracking-line"><i className="done" /><i className="done" /><i className="active" /><i /></div>
      <div className="tracking-labels"><span>Ordered</span><span>Picked up</span><span>At gate</span><span>Handoff</span></div>
    </div>
  );
  return (
    <div className="campus-map" aria-label="Illustrated route from the campus gate to the library">
      <svg viewBox="0 0 720 280" aria-hidden="true">
        <path className="campus-road" d="M28 230C126 219 130 112 248 126s178 92 268 5S606 48 694 37" />
        <path className="campus-route" d="M45 220C132 204 139 124 250 137s168 80 257 4" />
      </svg>
      <span className="campus-node gate"><i />Campus gate</span>
      <span className="campus-node library"><i />Library</span>
      <span className="campus-robot">M</span>
      <div className="map-status"><i /><span><small>Max robot</small><strong>Returning with your order</strong></span><b>2 min</b></div>
    </div>
  );
}

function JourneyCarousel() {
  const viewport = useRef(null);
  const activeRef = useRef(0);
  const wheelLocked = useRef(false);
  const [active, setActive] = useState(0);

  const show = (index) => {
    const next = Math.max(0, Math.min(journey.length - 1, index));
    const card = viewport.current?.children[next];
    if (!card) return;
    activeRef.current = next;
    setActive(next);
    viewport.current.scrollTo({
      left: card.offsetLeft - (viewport.current.clientWidth - card.offsetWidth) / 2,
      behavior: "smooth",
    });
  };

  const handleWheel = (event) => {
    const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
    const direction = Math.sign(delta);
    if (!direction) return;
    if (wheelLocked.current) {
      event.preventDefault();
      return;
    }
    if ((direction < 0 && activeRef.current === 0) || (direction > 0 && activeRef.current === journey.length - 1)) return;
    event.preventDefault();
    wheelLocked.current = true;
    show(activeRef.current + direction);
    window.setTimeout(() => { wheelLocked.current = false; }, 450);
  };

  const handleScroll = () => {
    const center = viewport.current.scrollLeft + viewport.current.clientWidth / 2;
    const next = Array.from(viewport.current.children).reduce((closest, card, index) => (
      Math.abs(card.offsetLeft + card.offsetWidth / 2 - center) < closest.distance
        ? { index, distance: Math.abs(card.offsetLeft + card.offsetWidth / 2 - center) }
        : closest
    ), { index: 0, distance: Infinity }).index;
    if (next !== activeRef.current) {
      activeRef.current = next;
      setActive(next);
    }
  };

  return (
    <>
      <div className="journey-viewport" ref={viewport} onWheel={handleWheel} onScroll={handleScroll}>
        {journey.map((step, index) => (
          <article className={`journey-card journey-${step.kind}`} key={step.kind}>
            <header><small>{step.label}</small><span>{String(index + 1).padStart(2, "0")} / 05</span></header>
            <div className="journey-copy"><h3>{step.title}</h3><p>{step.copy}</p></div>
            <JourneyVisual kind={step.kind} />
          </article>
        ))}
      </div>
      <div className="journey-controls">
        <span>Scroll or drag to move through the mission</span>
        <div className="journey-dots" aria-label="Mission story pages">
          {journey.map((step, index) => <button className={active === index ? "active" : ""} onClick={() => show(index)} aria-label={`Show ${step.label}`} key={step.kind} />)}
        </div>
        <div className="journey-arrows"><button onClick={() => show(active - 1)} disabled={active === 0} aria-label="Previous step">←</button><button onClick={() => show(active + 1)} disabled={active === journey.length - 1} aria-label="Next step">→</button></div>
      </div>
    </>
  );
}

const connections = [
  {
    mark: "AI",
    name: "OpenAI",
    state: "Reasoning",
    copy: "Turns a casual request into the item, quantity, budget and destination Max needs.",
  },
  {
    mark: "S",
    name: "Swiggy Instamart",
    state: "Live commerce",
    copy: "Finds the product, builds the cart and carries the exact order into checkout.",
  },
  {
    mark: "P",
    name: "Prava",
    state: "Sandbox approval",
    copy: "Asks the owner to approve one exact payment before Max is allowed to continue.",
  },
  {
    mark: "O",
    name: "ONDC",
    state: "Sandbox network",
    copy: "Opens the same request to more sellers without changing the mission around it.",
  },
  {
    mark: "T",
    name: "Telegram",
    state: "Owner channel",
    copy: "Starts requests and keeps the owner close when Max needs a decision or has an update.",
  },
  {
    mark: "M",
    name: "Max robot",
    state: "Physical handoff",
    copy: "Meets the delivery, secures the package and brings it to the person who asked.",
  },
];

export default function Landing() {
  return (
    <div className="landing-shell">
      <PublicNav />

      <main className="landing-main">
        <section className="landing-hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <h1 id="hero-title">
              An agent that shops online and <span>delivers across campus.</span>
            </h1>
            <p className="hero-summary">
              Text Max on Telegram. It finds the best option across Swiggy Instamart
              and ONDC, gets your payment approval, meets the delivery and brings
              the order to you on campus.
            </p>
            <div className="hero-actions">
              <a className="primary-link" href="/live">Watch a mission <Arrow /></a>
              <a className="text-link" href="#loop">See the full loop</a>
            </div>
          </div>

          <div className="mission-object" aria-label="Example Max mission">
            <div className="accent accent-plum" />
            <div className="accent accent-peach" />
            <div className="accent accent-rose" />
            <i className="orbit-dot orbit-dot-one" />
            <i className="orbit-dot orbit-dot-two" />
            <article className="mission-card mission-card-back back-one" aria-hidden="true">
              <span>Approval received</span>
            </article>
            <article className="mission-card mission-card-back back-two" aria-hidden="true">
              <span>Delivery tracked</span>
            </article>
            <article className="mission-card mission-card-front">
              <header className="mission-card-head">
                <div>
                  <small>Max · Current mission</small>
                  <strong>Bringing it to the library</strong>
                </div>
                <span className="live-pill"><i /> On it</span>
              </header>

              <div className="mission-request">
                <small>You said</small>
                <p>“Bring me a cold mango juice under ₹150.”</p>
              </div>

              <div className="mission-line-item">
                <div className="item-mark">B</div>
                <div>
                  <strong>B Natural Mango Juice</strong>
                  <span>1 L · Chilled</span>
                </div>
                <strong>₹110</strong>
              </div>

              <div className="mission-progress" aria-label="Mission progress">
                <div className="progress-track"><span /></div>
                {[
                  ["Found", "done"],
                  ["Approved", "done"],
                  ["Tracking", "active"],
                  ["Return", ""],
                ].map(([label, state]) => (
                  <div className={`progress-step ${state}`} key={label}>
                    <i />
                    <span>{label}</span>
                  </div>
                ))}
              </div>

              <footer className="mission-card-foot">
                <span>Swiggy Instamart</span>
                <span>Prava sandbox</span>
              </footer>
            </article>
          </div>

          <div className="capability-rail" aria-label="How Max completes an errand">
            <div><span>Ask</span><strong>Telegram or Mission Control</strong></div>
            <div><span>Find</span><strong>Swiggy Instamart or ONDC</strong></div>
            <div><span>Approve</span><strong>One exact amount in Prava</strong></div>
            <div><span>Receive</span><strong>Max brings it to where you are</strong></div>
          </div>
        </section>

        <section className="journey-section" aria-labelledby="journey-title">
          <header>
            <p className="section-label">One request, end to end</p>
            <h2 id="journey-title">Send one message. Max handles the moving parts.</h2>
          </header>
          <JourneyCarousel />
        </section>

        <section className="loop-section" id="loop">
          <div className="section-copy">
            <p className="section-label">The complete loop</p>
            <h2>The order is only half the job.</h2>
            <p>
              Max keeps the request, approval, delivery and physical handoff in one
              mission, then carries the order from the campus gate to where you are.
            </p>
          </div>
          <ol className="stage-list">
            {stages.map((stage) => (
              <li key={stage.number}>
                <span>{stage.number}</span>
                <div>
                  <h3>{stage.title}</h3>
                  <p>{stage.copy}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="system-section" id="system">
          <div className="system-copy">
            <p className="section-label">One mission record</p>
            <h2>See the whole run, not just the checkout.</h2>
            <p>
              Mission Control keeps the current task, exact quote, Prava approval,
              Swiggy updates, Telegram messages and robot state together.
            </p>
            <a className="primary-link compact" href="/live">Open Mission Control <Arrow /></a>
          </div>

          <div className="activity-window" aria-label="Example mission activity">
            <div className="activity-head">
              <div>
                <small>Mission 4F21</small>
                <strong>Live activity</strong>
              </div>
              <span className="window-status">Tracking order</span>
            </div>
            <ol>
              <li className="complete"><i /><div><strong>Request understood</strong><span>Cold mango juice · under ₹150</span></div><time>12:04</time></li>
              <li className="complete"><i /><div><strong>Exact quote approved</strong><span>Prava sandbox · ₹110</span></div><time>12:05</time></li>
              <li className="current"><i /><div><strong>Following the delivery</strong><span>Swiggy Instamart</span></div><time>Now</time></li>
              <li><i /><div><strong>Robot handoff</strong><span>Waiting for arrival</span></div><time>—</time></li>
            </ol>
          </div>
        </section>

        <section className="connections-section" aria-labelledby="connections-title">
          <header>
            <p className="section-label">The system behind Max</p>
            <h2 id="connections-title">One request. Six systems. No handoffs for you.</h2>
            <p>Each part does one job. Max keeps them moving as a single errand.</p>
          </header>
          <div className="connection-grid">
            {connections.map((connection) => (
              <article key={connection.name}>
                <div className="connection-mark">{connection.mark}</div>
                <div className="connection-title">
                  <h3>{connection.name}</h3>
                  <span>{connection.state}</span>
                </div>
                <p>{connection.copy}</p>
              </article>
            ))}
          </div>
        </section>

        <footer className="landing-footer">
          <div>
            <a className="wordmark" href="/">max<span>.</span></a>
            <p>A personal shopping and delivery agent built for college campuses.</p>
          </div>
          <a className="text-link" href="/live">Mission control <Arrow /></a>
        </footer>
      </main>
    </div>
  );
}
