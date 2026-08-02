import { useEffect, useState } from "react";
import { Arrow, PublicNav } from "./Landing.jsx";

const API = import.meta.env.VITE_API_URL
  || (import.meta.env.PROD ? window.location.origin : "http://127.0.0.1:8000");

const money = (minor, currency = "INR") =>
  minor == null ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(minor / 100);

const words = (value = "") => value.replaceAll("_", " ").toLowerCase();
const publicWords = (value = "") => words(value.replace(/^SIMULATED_/, ""));
const merchantName = (value = "") => {
  const name = value.toUpperCase();
  if (name.includes("SWIGGY")) return "Swiggy Instamart";
  if (name.includes("ONDC")) return "ONDC";
  return publicWords(value) || "Finding the right store";
};
const eventName = (value = "") => ({
  REQUEST_RECEIVED: "Request received",
  INTENT_VALIDATED: "Request understood",
  SIMULATED_QUOTE_CREATED: "Quote created",
  QUOTE_CREATED: "Quote created",
  PRAVA_SESSION_CREATED: "Approval requested",
  PRAVA_SANDBOX_SESSION_CREATED: "Approval requested",
  ORDER_CONFIRMED: "Order confirmed",
  ROBOT_DISPATCHED: "Robot dispatched",
}[value] || publicWords(value));
const componentName = (value = "") => ({
  orchestrator: "Max",
  agent: "OpenAI",
  commerce: "Commerce",
  payment: "Prava",
  robot: "Max robot",
}[value] || publicWords(value));

const phaseLabel = {
  DRAFT: "Understanding the request",
  NEEDS_CLARIFICATION: "Waiting on one detail",
  AWAITING_OWNER_APPROVAL: "Quote ready for approval",
  PAYMENT_APPROVAL_REQUIRED: "Waiting for Prava approval",
  PAYMENT_PERMISSION_READY: "Approval received",
  MERCHANT_CHECKOUT_IN_PROGRESS: "Placing the order",
  PAYMENT_RESULT_REPORT_REQUIRED: "Confirming payment",
  PAYMENT_DECLINED: "Payment declined",
  CHECKOUT_OUTCOME_UNKNOWN: "Checking the order",
  ORDER_CONFIRMED: "Order confirmed",
  READY_TO_DISPATCH: "Preparing the handoff",
  EN_ROUTE_TO_PICKUP: "Robot en route",
  AT_PICKUP: "Robot at pickup",
  ITEM_SECURED: "Package secured",
  RETURNING: "Bringing it back",
  COMPLETED: "Mission complete",
  CANCELLED: "Mission cancelled",
};

const ondcStages = [
  ["search / on_search", "Discover matching sellers and items"],
  ["select / on_select", "Lock the offer, quantity and quote"],
  ["init / on_init", "Prepare fulfilment and billing terms"],
  ["Prava approval", "Let the owner approve the exact amount"],
  ["confirm / on_confirm", "Place the approved order"],
  ["status / on_status", "Follow fulfilment on the same mission"],
  ["physical handoff", "Send Max to collect and return"],
];

const sensorReady = (value) => ["present", "ready", "online", "connected"].includes(value?.toLowerCase());

function usePublicData(path, refreshMs = 0) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stopped = false;
    const load = async () => {
      try {
        const response = await fetch(`${API}${path}`);
        if (!response.ok) throw new Error(`Feed unavailable (${response.status})`);
        const result = await response.json();
        if (!stopped) {
          setData(result);
          setError("");
        }
      } catch (exception) {
        if (!stopped) setError(exception.message);
      }
    };
    load();
    const timer = refreshMs ? window.setInterval(load, refreshMs) : null;
    return () => {
      stopped = true;
      if (timer) window.clearInterval(timer);
    };
  }, [path, refreshMs]);

  return { data, error };
}

function PublicShell({ children }) {
  return <div className="public-shell"><PublicNav /><main className="public-main">{children}</main></div>;
}

function EmptyMission({ error, history = false }) {
  return (
    <section className="mission-empty">
      <div className="empty-orbit"><i /><span /></div>
      <p className="section-label">Between errands</p>
      <h2>{error ? "The live feed is out of reach." : history ? "The first mission has not landed here yet." : "Max is not running a mission right now."}</h2>
      <p>{error || (history ? "A finished or paused run will appear here automatically." : "Previous runs are still available, with their full public timelines.")}</p>
      <a className="primary-link compact" href={history ? "/live" : "/history"}>{history ? "Open live view" : "Open history"} <Arrow /></a>
    </section>
  );
}

export function LiveMission() {
  const { data: mission, error } = usePublicData("/api/public/missions/active", 5000);
  const { data: robot, error: robotError } = usePublicData("/api/public/robot", 5000);
  const recentEvents = mission?.events.slice(-7) || [];
  const robotPhases = ["READY_TO_DISPATCH", "EN_ROUTE_TO_PICKUP", "AT_PICKUP", "ITEM_SECURED", "RETURNING", "COMPLETED"];
  const robotActive = mission && robotPhases.includes(mission.phase);

  return (
    <PublicShell>
      <header className="public-heading">
        <div>
          <p className="section-label">Live mission</p>
          <h1>From checkout to your hands.</h1>
        </div>
        <p>
          Follow what Max sees, where the handoff is and what it is doing next.
          Private addresses and controls stay with the owner.
        </p>
      </header>

      <section className="telemetry-grid" aria-live="polite">
        <article className="telemetry-card camera-telemetry">
          <header><div><small>Max vision</small><strong>Robot camera</strong></div><span className={robot?.connected ? "sensor-state ready" : "sensor-state"}>{robot?.connected ? "Heartbeat received" : "Waiting"}</span></header>
          <div className="telemetry-empty">
            <div className="camera-glyph"><i /></div>
            <h2>{robot?.connected && sensorReady(robot.camera) ? "Camera is connected." : "Waiting for camera."}</h2>
            <p>{robotError || (robot?.connected && sensorReady(robot.camera) ? "Max is reporting a camera. A public frame has not been sent yet." : "The Raspberry Pi has not sent a camera heartbeat yet.")}</p>
          </div>
          <footer><span>Camera · {publicWords(robot?.camera || "waiting")}</span><time>{robot?.last_seen_at ? `Seen ${new Date(robot.last_seen_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "No heartbeat"}</time></footer>
        </article>

        <article className="telemetry-card gps-telemetry">
          <header><div><small>Max location</small><strong>GPS position</strong></div><span className={robot?.connected ? "sensor-state ready" : "sensor-state"}>{robot?.connected ? publicWords(robot.status) : "Waiting"}</span></header>
          <div className="telemetry-empty">
            <div className="gps-glyph"><i /></div>
            <h2>{robot?.connected && sensorReady(robot.gps) ? "GPS is connected." : "Waiting for a GPS fix."}</h2>
            <p>{robotError || (robot?.connected && sensorReady(robot.gps) ? "Max is reporting GPS availability. Exact coordinates stay private." : "The robot has not reported a usable GPS heartbeat yet.")}</p>
          </div>
          <footer><span>GPS · {publicWords(robot?.gps || "waiting")}</span><span>Exact route is owner-only</span></footer>
        </article>
      </section>

      {!mission ? <EmptyMission error={error} /> : (
        <>

          <section className="mission-data-grid">
          <article className="live-mission-card">
            <header>
              <div>
                <small>Mission {mission.id.slice(0, 4).toUpperCase()}</small>
                <h2>{phaseLabel[mission.phase] || words(mission.phase)}</h2>
              </div>
              <span className="live-pill"><i /> Live</span>
            </header>

            <div className="live-product">
              <div className="item-mark">M</div>
              <div>
                <strong>{mission.product_name || "Finding the right item"}</strong>
                <span>{merchantName(mission.merchant)}{mission.quantity ? ` · Qty ${mission.quantity}` : ""}</span>
              </div>
              <strong>{money(mission.amount_minor, mission.currency || "INR")}</strong>
            </div>

            <div className="public-status-row">
              <div><span>Commerce</span><strong>{mission.product_name ? "Item found" : "Searching"}</strong></div>
              <div><span>Payment</span><strong>{mission.payment_status === "NOT_STARTED" ? "Awaiting approval" : publicWords(mission.payment_status)}</strong></div>
              <div><span>Bring it back</span><strong>{robotActive ? phaseLabel[mission.phase] : "After delivery"}</strong></div>
            </div>

            <footer>
              <span>{mission.environment === "production" ? "Live commerce" : "Prava sandbox"}</span>
              <time>Updated {new Date(mission.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
            </footer>
          </article>

          <article className="public-timeline">
            <header>
              <div><small>Safe event feed</small><h2>What Max has done</h2></div>
              <span>{recentEvents.length} updates</span>
            </header>
            <ol>
              {recentEvents.map((event) => (
                <li key={event.sequence}>
                  <i />
                  <div><strong>{eventName(event.event_type)}</strong><span>{componentName(event.component)}</span></div>
                  <time>{new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
                </li>
              ))}
            </ol>
          </article>
          </section>
        </>
      )}

      <section className="privacy-note">
        <span>Public by design</span>
        <p>The story is visible. The address, payment handoff and robot controls are not.</p>
      </section>
    </PublicShell>
  );
}

export function History() {
  const { data: missions, error } = usePublicData("/api/public/missions");
  const [selectedId, setSelectedId] = useState(null);
  const completed = missions?.filter((mission) => mission.phase === "COMPLETED").length || 0;
  const stopped = missions?.filter((mission) => ["CANCELLED", "PAYMENT_DECLINED"].includes(mission.phase)).length || 0;

  return (
    <PublicShell>
      <header className="public-heading history-heading">
        <div>
          <p className="section-label">All orders</p>
          <h1>Mission history.</h1>
        </div>
        <p>Review every order, approval, delivery update and robot handoff in one timeline.</p>
      </header>

      <section className="history-stats">
        <div><strong>{missions?.length ?? "—"}</strong><span>Total missions</span></div>
        <div><strong>{completed}</strong><span>Completed loops</span></div>
        <div><strong>{stopped}</strong><span>Stopped early</span></div>
      </section>

      {error || missions?.length === 0 ? <EmptyMission error={error} history /> : (
        <section className="history-layout">
          {!missions && <p className="loading-copy">Loading missions…</p>}
          {missions?.map((mission) => {
            const expanded = selectedId === mission.id;
            return (
              <article className={expanded ? "history-entry expanded" : "history-entry"} key={mission.id}>
                <button className="history-item" onClick={() => setSelectedId(expanded ? null : mission.id)} aria-expanded={expanded}>
                  <span className="history-mark">{mission.product_name?.[0] || "M"}</span>
                  <span>
                    <strong>{mission.product_name || "Mission in progress"}</strong>
                    <small>{new Date(mission.created_at).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })} · {phaseLabel[mission.phase] || words(mission.phase)}</small>
                  </span>
                  <b>{money(mission.amount_minor, mission.currency || "INR")}</b>
                  <Arrow />
                </button>
                {expanded && (
                  <div className="history-detail">
                    <header>
                      <div><small>Mission {mission.id.slice(0, 8).toUpperCase()}</small><h2>Complete mission log</h2></div>
                      <strong>{mission.events.length} events</strong>
                    </header>
                    <div className="history-meta">
                      <span>{merchantName(mission.merchant)}</span>
                      <span>{mission.quantity ? `Quantity ${mission.quantity}` : "Quantity pending"}</span>
                      <span>{phaseLabel[mission.phase] || words(mission.phase)}</span>
                      <span>Updated {new Date(mission.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>
                    </div>
                    <div className="history-statuses">
                      <div><span>Commerce</span><strong>{publicWords(mission.commerce_status)}</strong></div>
                      <div><span>Payment</span><strong>{publicWords(mission.payment_status)}</strong></div>
                      <div><span>Checkout</span><strong>{publicWords(mission.checkout_status)}</strong></div>
                      <div><span>Fulfilment</span><strong>{publicWords(mission.fulfilment_status)}</strong></div>
                    </div>
                    <ol>
                      {mission.events.map((event) => (
                        <li key={event.sequence}>
                          <i />
                          <div><strong>{eventName(event.event_type)}</strong><span>{componentName(event.component)} · result: {phaseLabel[event.phase_after] || publicWords(event.phase_after)}</span></div>
                          <time>{new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}
    </PublicShell>
  );
}

export function OndcSandbox() {
  return (
    <PublicShell>
      <section className="ondc-hero">
        <div className="ondc-copy">
          <p className="section-label">ONDC sandbox</p>
          <h1>The catalog is wider than one app.</h1>
          <p>
            Max can send the same request into ONDC, compare what comes back,
            and keep the chosen offer inside the same mission record.
          </p>
          <a className="primary-link" href="/live">See Mission Control <Arrow /></a>
        </div>

        <div className="ondc-object" aria-label="ONDC offer matching illustration">
          <div className="route-line"><i /><i /><i /></div>
          <article className="request-card">
            <small>Max request</small>
            <strong>Cold mango juice · 1 litre</strong>
            <span>Bring it to the college library</span>
          </article>
          <article className="offer-card offer-one"><span>A</span><div><small>Seller app</small><strong>Offer returned</strong></div><b>01</b></article>
          <article className="offer-card offer-two"><span>B</span><div><small>Seller app</small><strong>Offer returned</strong></div><b>02</b></article>
          <article className="offer-card offer-three"><span>C</span><div><small>Seller app</small><strong>Offer returned</strong></div><b>03</b></article>
          <div className="chosen-offer"><span>Chosen for the mission</span><i /></div>
        </div>
      </section>

      <section className="ondc-reasons">
        <article><span>01</span><h2>One request</h2><p>Max turns the owner’s need into a product search once.</p></article>
        <article><span>02</span><h2>Many sellers</h2><p>ONDC returns offers across its sandbox network for comparison.</p></article>
        <article><span>03</span><h2>One record</h2><p>The chosen offer rejoins the same approval, delivery and handoff flow.</p></article>
      </section>

      <section className="ondc-workbench" aria-labelledby="ondc-workbench-title">
        <header>
          <div><p className="section-label">Commerce workbench</p><h2 id="ondc-workbench-title">How an ONDC order moves through Max.</h2></div>
          <div className="ondc-chips"><span>ONDC sandbox</span><span>Retail B2C</span><span>Delivery</span></div>
        </header>

        <div className="ondc-workbench-grid">
          <article className="protocol-card">
            <header><div><small>Transaction path</small><strong>Request → confirmed order</strong></div><span>7 checkpoints</span></header>
            <ol>
              {ondcStages.map(([action, copy], index) => (
                <li key={action}>
                  <b>{String(index + 1).padStart(2, "0")}</b>
                  <div><strong>{action}</strong><span>{copy}</span></div>
                  <i />
                </li>
              ))}
            </ol>
          </article>

          <aside className="protocol-inspector">
            <header><small>Protocol inspector</small><strong>What stays attached to the mission</strong></header>
            <dl>
              <div><dt>Buyer intent</dt><dd>Item, quantity, budget</dd></div>
              <div><dt>Offer</dt><dd>Seller, quote, fulfilment</dd></div>
              <div><dt>Approval</dt><dd>Exact amount through Prava</dd></div>
              <div><dt>Order</dt><dd>Confirmation and status events</dd></div>
              <div><dt>Handoff</dt><dd>Delivery arrival → Max robot</dd></div>
            </dl>
            <div className="protocol-boundary">
              <span>Owner boundary</span>
              <p>Credentials, address and transaction controls never appear on this public page.</p>
            </div>
          </aside>
        </div>
      </section>

      <section className="sandbox-note">
        <div><span>Network</span><strong>ONDC sandbox</strong></div>
        <div><span>Commerce path</span><strong>Search → confirm</strong></div>
        <div><span>Payment boundary</span><strong>Prava approval</strong></div>
        <p>The ONDC path joins the same mission record used by the live commerce and robot handoff flow.</p>
      </section>
    </PublicShell>
  );
}
