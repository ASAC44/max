import { useEffect, useRef, useState } from "react";
import TeleopPanel from "./TeleopPanel.jsx";

const API = import.meta.env.VITE_API_URL
  || (import.meta.env.PROD ? window.location.origin : "http://127.0.0.1:8000");

const money = (minor, currency = "INR") =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(minor / 100);

const newCommand = () => crypto.randomUUID();

export default function App() {
  const [token, setToken] = useState("");
  const [request, setRequest] = useState("get 1 milk under ₹300 for work");
  const [reply, setReply] = useState("");
  const [mission, setMission] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [automationFailed, setAutomationFailed] = useState(false);
  const [robotStatus, setRobotStatus] = useState(null);
  const paymentAutomation = useRef({ missionId: null, polling: false, checkoutStarted: false });

  const call = async (path, options = {}) => {
    if (!token) throw new Error("Enter the operator token first.");
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail;
      const exception = new Error(
        typeof detail === "string" ? detail : detail?.message || `Request failed (${response.status})`,
      );
      exception.missionId = detail?.mission_id;
      throw exception;
    }
    return payload;
  };

  const run = async (operation) => {
    setBusy(true);
    setError("");
    try {
      const next = await operation();
      setMission(next);
      const url = new URL(window.location.href);
      url.searchParams.set("mission", next.id);
      history.replaceState(null, "", url);
    } catch (exception) {
      setError(exception.message);
      if (exception.missionId) {
        try {
          const recovered = await call(`/api/missions/${exception.missionId}`);
          setMission(recovered);
          const url = new URL(window.location.href);
          url.searchParams.set("mission", recovered.id);
          history.replaceState(null, "", url);
        } catch {
          // Keep the original safe error visible if recovery also fails.
        }
      }
    } finally {
      setBusy(false);
    }
  };

  const command = (name, extra = {}) => run(() => call(
    `/api/missions/${mission.id}/commands/${name}`,
    {
      method: "POST",
      body: JSON.stringify({ expected_version: mission.version, command_id: newCommand(), ...extra }),
    },
  ));

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("mission");
    if (id && token) run(() => call(`/api/missions/${id}`));
    // Token deliberately stays in memory and is never written to browser storage.
  }, [token]);

  useEffect(() => {
    if (!mission || !token) return undefined;
    const livePhases = [
      "ORDER_CONFIRMED",
      "READY_TO_DISPATCH",
      "EN_ROUTE_TO_PICKUP",
      "AT_PICKUP",
      "ITEM_SECURED",
      "RETURNING",
    ];
    if (!livePhases.includes(mission.phase)) return undefined;
    let stopped = false;
    const refreshMission = async () => {
      try {
        const next = await call("/api/missions/active");
        if (!stopped) {
          setMission(next);
          const url = new URL(window.location.href);
          url.searchParams.set("mission", next.id);
          history.replaceState(null, "", url);
        }
      } catch {
        // Keep the last authoritative state visible during a transient refresh failure.
      }
    };
    const timer = window.setInterval(refreshMission, 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [mission?.id, mission?.phase, token]);

  useEffect(() => {
    if (!token) {
      setRobotStatus(null);
      return undefined;
    }
    let stopped = false;
    const refreshRobot = async () => {
      try {
        const next = await call("/api/robot/v1/status");
        if (!stopped) setRobotStatus(next);
      } catch {
        if (!stopped) setRobotStatus(null);
      }
    };
    refreshRobot();
    const timer = window.setInterval(refreshRobot, 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [token]);

  useEffect(() => {
    if (!mission || !token) return undefined;
    if (paymentAutomation.current.missionId !== mission.id) {
      paymentAutomation.current = { missionId: mission.id, polling: false, checkoutStarted: false };
      setAutomationFailed(false);
    }
    let stopped = false;

    const execute = async (ready) => {
      if (paymentAutomation.current.checkoutStarted) return;
      paymentAutomation.current.checkoutStarted = true;
      setBusy(true);
      setError("");
      try {
        const next = await call(`/api/missions/${ready.id}/commands/execute-checkout`, {
          method: "POST",
          body: JSON.stringify({ expected_version: ready.version, command_id: newCommand() }),
        });
        if (!stopped) setMission(next);
      } catch (exception) {
        if (!stopped) {
          setError(exception.message);
          setAutomationFailed(true);
          if (exception.missionId) {
            try {
              setMission(await call(`/api/missions/${exception.missionId}`));
            } catch {
              // Preserve the original safe error.
            }
          }
        }
      } finally {
        if (!stopped) setBusy(false);
      }
    };

    const poll = async () => {
      if (paymentAutomation.current.polling || mission.phase !== "PAYMENT_APPROVAL_REQUIRED") return;
      paymentAutomation.current.polling = true;
      try {
        const next = await call(`/api/missions/${mission.id}/commands/refresh-payment`, {
          method: "POST",
          body: JSON.stringify({ expected_version: mission.version, command_id: newCommand() }),
        });
        if (stopped) return;
        if (next.phase === "PAYMENT_PERMISSION_READY") await execute(next);
        else setMission(next);
      } catch (exception) {
        if (!stopped) setError(exception.message);
      } finally {
        paymentAutomation.current.polling = false;
      }
    };

    if (mission.phase === "PAYMENT_APPROVAL_REQUIRED") {
      poll();
      const timer = window.setInterval(poll, 2000);
      return () => { stopped = true; window.clearInterval(timer); };
    }
    if (mission.phase === "PAYMENT_PERMISSION_READY") execute(mission);
    return () => { stopped = true; };
  }, [mission?.id, mission?.phase, mission?.version, token]);

  useEffect(() => {
    if (!mission?.delivery || !token || !["ORDER_CONFIRMED", "EN_ROUTE_TO_PICKUP", "AT_PICKUP", "ITEM_SECURED", "RETURNING"].includes(mission.phase)) return undefined;
    const timer = window.setInterval(async () => {
      try { setMission(await call(`/api/missions/${mission.id}`)); } catch (exception) { setError(exception.message); }
    }, 10000);
    return () => window.clearInterval(timer);
  }, [mission?.id, mission?.phase, Boolean(mission?.delivery), token]);

  const create = () => run(() => call("/api/missions", {
    method: "POST",
    headers: { "Idempotency-Key": newCommand() },
    body: JSON.stringify({ text: request }),
  }));

  const sendReply = () => command("reply", { text: reply });
  const approve = () => command("approve", { quote_hash: mission.quote_hash, simulated_outcome: "decline" });
  const refreshQuote = () => command("requote", { amount_minor: mission.quote.amount_minor });
  const copyVerificationLink = async () => {
    const url = mission.payment_action.approval_url;
    try {
      await navigator.clipboard.writeText(url);
      window.alert("One-time Prava link copied. Open it first on the passkey-capable device.");
    } catch {
      window.prompt("Copy this one-time Prava link without opening it:", url);
    }
  };
  const clearMission = () => {
    setMission(null);
    setError("");
    const url = new URL(window.location.href);
    url.searchParams.delete("mission");
    history.replaceState(null, "", url);
  };
  const closeUnresolved = async () => {
    if (!window.confirm("The merchant outcome is still unknown. Close this mission without claiming it was cancelled?")) return;
    setBusy(true);
    setError("");
    try {
      await call(`/api/missions/${mission.id}/commands/close-unresolved`, {
        method: "POST",
        body: JSON.stringify({ expected_version: mission.version, command_id: newCommand() }),
      });
      clearMission();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  };
  const retryCheckout = () => {
    paymentAutomation.current.checkoutStarted = false;
    setAutomationFailed(false);
    command("execute-checkout");
  };

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">MAX / PHASE 3A</p>
          <h1>Mission control</h1>
        </div>
        <span className="truth">
          {mission?.environment === "staged_demo"
            ? "MIXED · STAGED PACKAGE + LOCAL ROBOT SIM"
            : `${(mission?.environment || "local").toUpperCase()} · ${(mission?.agent_mode || "simulated").toUpperCase()}`}
        </span>
      </header>

      <section className="compose panel">
        <label>
          Operator token <span>kept in memory only</span>
          <input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" />
        </label>
        <label className="wide">
          Owner request
          <input value={request} onChange={(event) => setRequest(event.target.value)} />
        </label>
        <button onClick={create} disabled={busy || !token}>Create mission</button>
      </section>

      {error && <p role="alert" className="error">{error}</p>}

      {token && <TeleopPanel api={API} token={token} />}

      {token && (
        <section className="panel robot-health">
          <div>
            <p className="eyebrow">UNIFIED PI AGENT</p>
            <strong>
              {robotStatus?.connected
                ? `${robotStatus.robot.robot_id} · ${robotStatus.robot.status}`
                : "OFFLINE / HEARTBEAT STALE"}
            </strong>
          </div>
          <span className="truth">
            AUTONOMOUS MOTION {robotStatus?.motion_enabled ? "ENABLED" : "DISABLED"}
          </span>
          {robotStatus?.robot && (
            <div className="subsystems">
              {Object.entries(robotStatus.robot.subsystems).map(([name, state]) => (
                <small key={name}>{name}: {state}</small>
              ))}
            </div>
          )}
        </section>
      )}

      {mission && (
        <>
          <section className="status-grid">
            <article className="hero panel">
              <div className="badges">
                <span>{mission.environment}</span><span>{mission.agent_mode} agent</span><span>v{mission.version}</span>
              </div>
              <p className="eyebrow">CURRENT PHASE</p>
              <h2>{mission.phase.replaceAll("_", " ")}</h2>
              <p>{mission.request_text}</p>
              {mission.clarification_question && (
                <div className="clarify">
                  <strong>{mission.clarification_question}</strong>
                  <div><input value={reply} onChange={(event) => setReply(event.target.value)} /><button onClick={sendReply} disabled={busy}>Reply</button></div>
                </div>
              )}
            </article>

            <article className="panel quote">
              <p className="eyebrow">IMMUTABLE QUOTE</p>
              {mission.quote ? (
                <>
                  <h3>{mission.quote.product_name}</h3>
                  <strong>{money(mission.quote.amount_minor, mission.quote.currency)}</strong>
                  <p>{mission.quote.quantity} × {mission.quote.merchant}</p>
                  <small>revision {mission.quote.revision} · {mission.quote.environment}</small>
                </>
              ) : <p>Waiting for a complete request.</p>}
            </article>
          </section>

          <section className="panel controls">
            <p className="eyebrow">VALID COMMANDS</p>
            <div>
              {mission.phase === "AWAITING_OWNER_APPROVAL" && mission.quote.environment !== "production" && mission.commerce_status !== "QUOTE_EXPIRED" && <button onClick={approve} disabled={busy}>Approve exact quote</button>}
              {mission.phase === "AWAITING_OWNER_APPROVAL" && mission.quote.environment === "production" && <button onClick={approve} disabled={busy}>Retry Prava setup</button>}
              {mission.phase === "PAYMENT_APPROVAL_REQUIRED" && mission.payment_action && <button onClick={() => window.open(mission.payment_action.approval_url, "_blank", "noopener,noreferrer")}>Open verification on this device</button>}
              {mission.phase === "PAYMENT_APPROVAL_REQUIRED" && mission.payment_action && <button onClick={copyVerificationLink}>Copy one-time link for phone</button>}
              {mission.phase === "PAYMENT_APPROVAL_REQUIRED" && <span>Waiting for Prava approval; Max will continue automatically.</span>}
              {mission.phase === "PAYMENT_PERMISSION_READY" && !automationFailed && <span>Prava approved; Max is opening Swiggy automatically.</span>}
              {mission.phase === "PAYMENT_PERMISSION_READY" && automationFailed && <button onClick={retryCheckout} disabled={busy}>Retry browser preparation</button>}
              {mission.phase === "PAYMENT_RESULT_REPORT_REQUIRED" && <button onClick={() => command("report-payment-result")} disabled={busy}>Retry Prava result report</button>}
              {mission.phase === "ORDER_CONFIRMED" && mission.delivery && !mission.delivery.armed && <button onClick={() => command("arm-dispatch")} disabled={busy}>Arm ETA dispatch</button>}
              {mission.delivery?.armed && mission.phase === "ORDER_CONFIRMED" && <span>Robot armed; waiting for calculated dispatch time.</span>}
              {mission.commerce_status === "QUOTE_EXPIRED" && mission.quote.environment !== "production" && <button onClick={refreshQuote} disabled={busy}>Refresh expired quote</button>}
              {["DRAFT", "NEEDS_CLARIFICATION", "AWAITING_OWNER_APPROVAL", "PAYMENT_APPROVAL_REQUIRED", "PAYMENT_PERMISSION_READY"].includes(mission.phase) && <button className="secondary" onClick={() => command("cancel")} disabled={busy}>Cancel mission</button>}
              {mission.environment === "staged_demo" && ["ORDER_CONFIRMED", "READY_TO_DISPATCH"].includes(mission.phase) && <button className="secondary" onClick={() => command("cancel")} disabled={busy}>Cancel staged mission</button>}
              {mission.phase === "CHECKOUT_OUTCOME_UNKNOWN" && <button className="secondary" onClick={closeUnresolved} disabled={busy}>Close unresolved mission</button>}
              {["PAYMENT_DECLINED", "COMPLETED", "CANCELLED", "CLOSED_UNRESOLVED"].includes(mission.phase) && <button className="secondary" onClick={clearMission} disabled={busy}>Start new mission</button>}
              {["PAYMENT_DECLINED", "ORDER_CONFIRMED"].includes(mission.phase) && mission.environment !== "staged_demo" && <button onClick={() => command("start-staged")} disabled={busy}>Create separate staged fulfilment</button>}
              {mission.environment === "staged_demo" && mission.phase === "ORDER_CONFIRMED" && <button onClick={() => command("package-ready")} disabled={busy}>Record PACKAGE_READY</button>}
              {mission.environment === "staged_demo" && mission.phase === "READY_TO_DISPATCH" && !mission.robot_job && <button onClick={() => command("run-robot")} disabled={busy}>Send fail-closed Pi job</button>}
              {mission.robot_job && <span>Pi job {mission.robot_job.status.toLowerCase()} · {mission.robot_job.trigger_source.toLowerCase()} trigger</span>}
            </div>
          </section>

          {mission.delivery && (
            <section className="panel">
              <p className="eyebrow">DELIVERY TRACKING</p>
              <h3>{mission.delivery.status.replaceAll("_", " ")}</h3>
              <p>Order {mission.delivery.order_reference || "needs manual binding"}</p>
              {mission.delivery.eta_at && <p>ETA: {new Date(mission.delivery.eta_at).toLocaleTimeString()}</p>}
              {mission.delivery.dispatch_at && <p>Robot departure: {new Date(mission.delivery.dispatch_at).toLocaleTimeString()}</p>}
              <p>Robot: {mission.delivery.robot_status.replaceAll("_", " ")}</p>
              {mission.delivery.alert && <p role="alert" className="error">{mission.delivery.alert}</p>}
            </section>
          )}

          <section className="provider-grid">
            {["commerce", "payment", "checkout", "fulfilment", "notification"].map((name) => (
              <article className="panel provider" key={name}>
                <p>{name}</p>
                <strong>{mission[`${name}_status`]}</strong>
              </article>
            ))}
          </section>

          {mission.commerce_status.startsWith("SWIGGY_") && (
            <section className="panel live-order">
              <p className="eyebrow">LIVE SWIGGY STATUS</p>
              <h2>{mission.commerce_status.slice(7).replaceAll("_", " ")}</h2>
              <p>Every distinct provider transition is stored in the timeline and forwarded to the Pi. Motor motion remains disabled.</p>
            </section>
          )}

          {mission.source_order_events?.length > 0 && (
            <section className="panel live-order">
              <p className="eyebrow">SWIGGY DELIVERY TIMELINE</p>
              <ol>
                {mission.source_order_events.map((event) => (
                  <li key={`${event.sequence}-${event.event_type}`}>
                    <strong>{event.payload.normalized_status?.replaceAll("_", " ") || event.event_type.replaceAll("_", " ")}</strong>
                    <small>{event.payload.eta_text || "ETA unavailable"} · {new Date(event.created_at).toLocaleTimeString()}</small>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="panel timeline">
            <div className="section-title"><div><p className="eyebrow">AUTHORITATIVE EVENT LOG</p><h2>Timeline</h2></div><button className="secondary" onClick={() => run(() => call(`/api/missions/${mission.id}`))} disabled={busy}>Refresh</button></div>
            <ol>
              {mission.events.map((event) => (
                <li key={event.sequence}>
                  <span>{String(event.sequence).padStart(2, "0")}</span>
                  <div><strong>{event.event_type.replaceAll("_", " ")}</strong><small>{event.component}{event.provider ? ` · ${event.provider}` : ""} · {event.environment}{event.human_intervened ? " · human" : ""} · {new Date(event.created_at).toLocaleTimeString()}</small></div>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </main>
  );
}
