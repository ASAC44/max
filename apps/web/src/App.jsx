import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

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

  const create = () => run(() => call("/api/missions", {
    method: "POST",
    headers: { "Idempotency-Key": newCommand() },
    body: JSON.stringify({ text: request }),
  }));

  const sendReply = () => command("reply", { text: reply });
  const approve = () => command("approve", { quote_hash: mission.quote_hash, simulated_outcome: "decline" });
  const refreshQuote = () => command("requote", { amount_minor: mission.quote.amount_minor });

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
              {mission.phase === "AWAITING_OWNER_APPROVAL" && mission.commerce_status !== "QUOTE_EXPIRED" && <button onClick={approve} disabled={busy}>Approve exact quote → simulated decline</button>}
              {mission.commerce_status === "QUOTE_EXPIRED" && <button onClick={refreshQuote} disabled={busy}>Refresh expired quote</button>}
              {["DRAFT", "NEEDS_CLARIFICATION", "AWAITING_OWNER_APPROVAL", "PAYMENT_PERMISSION_READY", "ORDER_CONFIRMED", "READY_TO_DISPATCH"].includes(mission.phase) && <button className="secondary" onClick={() => command("cancel")} disabled={busy}>Cancel</button>}
              {mission.phase === "PAYMENT_DECLINED" && <button onClick={() => command("start-staged")} disabled={busy}>Create separate staged fulfilment</button>}
              {mission.environment === "staged_demo" && mission.phase === "ORDER_CONFIRMED" && <button onClick={() => command("package-ready")} disabled={busy}>Record PACKAGE_READY</button>}
              {mission.environment === "staged_demo" && mission.phase === "READY_TO_DISPATCH" && <button onClick={() => command("run-robot")} disabled={busy}>Run labeled robot simulation</button>}
            </div>
          </section>

          <section className="provider-grid">
            {["commerce", "payment", "checkout", "fulfilment", "notification"].map((name) => (
              <article className="panel provider" key={name}>
                <p>{name}</p>
                <strong>{mission[`${name}_status`]}</strong>
              </article>
            ))}
          </section>

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
