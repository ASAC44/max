import { useCallback, useEffect, useRef, useState } from "react";

import {
  AUDIO_MODES,
  DRIVE_MODES,
  KEY_BY_CODE,
  KEY_LABELS,
  MOVEMENT_OPPOSITES,
  TELEOP_PROTOCOL_VERSION,
  inputMessage,
  isEditableTarget,
  simpleMessage,
  websocketUrl,
} from "./teleopProtocol.js";

const EMPTY_STATUS = {
  feature_enabled: false,
  emergency_stop: true,
  reset_pending: false,
  controls_enabled: false,
  controller_online: false,
  agent_online: false,
  agent_armed: false,
  active_keys: [],
  agent_keys: [],
  round_trip_ms: null,
  deadman_ms: null,
};

const keyOrder = ["W", "A", "S", "D", "SPACE", "1", "2", "3", "4", "5"];

export default function TeleopPanel({ api, token }) {
  const [requested, setRequested] = useState(false);
  const [connection, setConnection] = useState("idle");
  const [keyboardCapture, setKeyboardCapture] = useState(false);
  const [status, setStatus] = useState(EMPTY_STATUS);
  const [error, setError] = useState("");
  const [reconnectCount, setReconnectCount] = useState(0);
  const socketRef = useRef(null);
  const pressedRef = useRef(new Set());
  const sequenceRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const requestedRef = useRef(false);
  const keyboardCaptureRef = useRef(false);
  const statusRef = useRef(EMPTY_STATUS);

  useEffect(() => {
    requestedRef.current = requested;
  }, [requested]);

  useEffect(() => {
    keyboardCaptureRef.current = keyboardCapture;
  }, [keyboardCapture]);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const sendJson = useCallback((value) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(value));
    return true;
  }, []);

  const sendInput = useCallback((keys, { force = false } = {}) => {
    if (connection !== "online") return false;
    if (!force && (!keyboardCaptureRef.current || !statusRef.current.controls_enabled)) return false;
    sequenceRef.current += 1;
    return sendJson(inputMessage(sequenceRef.current, keys));
  }, [connection, sendJson]);

  const releaseLocal = useCallback((reason = "local_release") => {
    const hadKeys = pressedRef.current.size > 0;
    pressedRef.current.clear();
    if (hadKeys || reason !== "connection_lost") sendInput([], { force: true });
    setKeyboardCapture(false);
  }, [sendInput]);

  useEffect(() => {
    if (!token) {
      setStatus(EMPTY_STATUS);
      return undefined;
    }
    let stopped = false;
    const refresh = async () => {
      try {
        const response = await fetch(`${api}/api/teleop/status`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) throw new Error(`Status failed (${response.status})`);
        const next = await response.json();
        if (!stopped && connection !== "online") setStatus(next);
      } catch (exception) {
        if (!stopped && connection !== "online") {
          setError(exception.message);
          setStatus(EMPTY_STATUS);
        }
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [api, token, connection]);

  useEffect(() => {
    if (!requested || !token) return undefined;
    let disposed = false;

    const scheduleReconnect = () => {
      if (disposed || !requestedRef.current) return;
      const attempt = reconnectAttemptRef.current;
      const base = Math.min(10_000, 500 * (2 ** attempt));
      const delay = base + Math.floor(Math.random() * Math.max(100, base / 4));
      reconnectAttemptRef.current = Math.min(6, attempt + 1);
      setConnection("reconnecting");
      reconnectTimerRef.current = window.setTimeout(() => {
        setReconnectCount((value) => value + 1);
      }, delay);
    };

    const connect = () => {
      setConnection(reconnectAttemptRef.current ? "reconnecting" : "connecting");
      setError("");
      const socket = new WebSocket(websocketUrl(api));
      socketRef.current = socket;

      socket.addEventListener("open", () => {
        setConnection("authenticating");
        socket.send(JSON.stringify({
          type: "auth",
          protocol_version: TELEOP_PROTOCOL_VERSION,
          token,
        }));
      });

      socket.addEventListener("message", (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          setError("Backend sent invalid control data.");
          socket.close(4400, "invalid data");
          return;
        }
        if (message.type === "ready") {
          reconnectAttemptRef.current = 0;
          sequenceRef.current = 0;
          pressedRef.current.clear();
          setKeyboardCapture(false);
          setConnection("online");
          setStatus(message);
          setError("");
          return;
        }
        if (message.type === "status") {
          setStatus(message);
          if (message.controls_enabled) setError("");
          if (!message.controls_enabled) {
            pressedRef.current.clear();
            setKeyboardCapture(false);
          }
          return;
        }
        if (message.type === "agent_ack") {
          setStatus((current) => ({
            ...current,
            agent_keys: message.keys,
            round_trip_ms: message.round_trip_ms,
          }));
          return;
        }
        if (message.type === "input_ack") {
          setStatus((current) => ({
            ...current,
            active_keys: message.active_keys,
          }));
          return;
        }
        if (message.type === "error") {
          setError(message.message || message.code || "Control error");
          if (["emergency_stop", "agent_offline", "agent_rejected_input"].includes(message.code)) {
            pressedRef.current.clear();
            setKeyboardCapture(false);
          }
        }
      });

      socket.addEventListener("close", (event) => {
        if (socketRef.current === socket) socketRef.current = null;
        pressedRef.current.clear();
        setKeyboardCapture(false);
        setConnection("disconnected");
        setStatus((current) => ({
          ...current,
          controller_online: false,
          active_keys: [],
          agent_keys: [],
        }));
        if (event.code === 4401) {
          setError("Operator token was rejected.");
          setRequested(false);
          return;
        }
        if (event.code === 4403) {
          setError("This dashboard origin is not allowed to control the bot.");
          setRequested(false);
          return;
        }
        if (event.code === 4409) {
          setError("Another authorized controller currently owns the control lease.");
        } else if (requestedRef.current) {
          setError("Control connection lost. Keys were released; reconnecting.");
        }
        scheduleReconnect();
      });

      socket.addEventListener("error", () => {
        setError("Real-time control connection failed.");
      });
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        sequenceRef.current += 1;
        socket.send(JSON.stringify(inputMessage(sequenceRef.current, [])));
        socket.close(1000, "controller released");
      } else if (socket) {
        socket.close();
      }
      socketRef.current = null;
      pressedRef.current.clear();
      setKeyboardCapture(false);
    };
  }, [api, token, requested, reconnectCount]);

  useEffect(() => {
    if (!requested || connection !== "online") return undefined;
    const heartbeat = window.setInterval(() => {
      sendJson(simpleMessage("heartbeat"));
    }, 2000);
    return () => window.clearInterval(heartbeat);
  }, [requested, connection, sendJson]);

  useEffect(() => {
    if (!keyboardCapture || connection !== "online") return undefined;

    const onKeyDown = (event) => {
      const key = KEY_BY_CODE[event.code];
      if (!key || isEditableTarget(event.target)) return;
      event.preventDefault();
      if (!statusRef.current.controls_enabled) return;
      const next = new Set(pressedRef.current);
      for (const [left, right] of MOVEMENT_OPPOSITES) {
        if (key === left) next.delete(right);
        if (key === right) next.delete(left);
      }
      if (DRIVE_MODES.includes(key)) {
        for (const mode of DRIVE_MODES) next.delete(mode);
      }
      if (AUDIO_MODES.includes(key)) {
        for (const mode of AUDIO_MODES) next.delete(mode);
      }
      if (next.has(key)) return;
      next.add(key);
      pressedRef.current = next;
      sendInput(next);
    };

    const onKeyUp = (event) => {
      const key = KEY_BY_CODE[event.code];
      if (!key || isEditableTarget(event.target)) return;
      event.preventDefault();
      if (!pressedRef.current.has(key)) return;
      const next = new Set(pressedRef.current);
      next.delete(key);
      pressedRef.current = next;
      sendInput(next, { force: true });
    };

    const release = () => releaseLocal("window_inactive");
    window.addEventListener("keydown", onKeyDown, { capture: true });
    window.addEventListener("keyup", onKeyUp, { capture: true });
    window.addEventListener("blur", release);
    window.addEventListener("pagehide", release);
    document.addEventListener("visibilitychange", release);
    const refresh = window.setInterval(() => {
      if (pressedRef.current.size) sendInput(pressedRef.current);
    }, 100);
    return () => {
      window.removeEventListener("keydown", onKeyDown, { capture: true });
      window.removeEventListener("keyup", onKeyUp, { capture: true });
      window.removeEventListener("blur", release);
      window.removeEventListener("pagehide", release);
      document.removeEventListener("visibilitychange", release);
      window.clearInterval(refresh);
      pressedRef.current.clear();
    };
  }, [keyboardCapture, connection, releaseLocal, sendInput]);

  const takeControl = () => {
    setError("");
    setRequested(true);
  };

  const releaseControl = () => {
    releaseLocal("operator_release");
    setRequested(false);
    setConnection("idle");
  };

  const enableKeyboard = () => {
    if (!status.controls_enabled) return;
    pressedRef.current.clear();
    setError("");
    setKeyboardCapture(true);
  };

  const emergencyStop = async () => {
    pressedRef.current.clear();
    setKeyboardCapture(false);
    if (sendJson(simpleMessage("emergency_stop"))) return;
    try {
      const response = await fetch(`${api}/api/teleop/emergency-stop`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error(`Emergency stop failed (${response.status})`);
      setStatus(await response.json());
      setError("");
    } catch (exception) {
      setError(`${exception.message}. The live link is already fail-safe released.`);
    }
  };

  const resetEmergencyStop = () => {
    pressedRef.current.clear();
    setKeyboardCapture(false);
    if (!sendJson(simpleMessage("reset_estop"))) {
      setError("Emergency-stop reset could not reach the backend.");
    }
  };

  const online = connection === "online";
  const activeKeys = new Set(status.agent_keys || status.active_keys || []);

  return (
    <section className={`panel teleop ${keyboardCapture ? "teleop-capturing" : ""}`}>
      <div className="teleop-heading">
        <div>
          <p className="eyebrow">REMOTE TELEOPERATION</p>
          <h2>Laptop keyboard → AWS → Pi</h2>
          <p className="teleop-copy">
            Authoritative state snapshots refresh every 100 ms while held. Any disconnect releases every key.
          </p>
        </div>
        <div className="teleop-badges" aria-live="polite">
          <span className={`status-dot ${online ? "good" : ""}`}>LINK {connection.toUpperCase()}</span>
          <span className={`status-dot ${status.agent_online ? "good" : ""}`}>
            PI AGENT {status.agent_online ? "ONLINE" : "OFFLINE"}
          </span>
          <span className={`status-dot ${status.emergency_stop ? "danger" : "good"}`}>
            E-STOP {status.emergency_stop ? "LATCHED" : "CLEAR"}
          </span>
        </div>
      </div>

      <div className="teleop-layout">
        <div className="key-map" aria-label="Remote control key map">
          {keyOrder.map((key) => (
            <div className={`key-command ${activeKeys.has(key) ? "active" : ""}`} key={key}>
              <kbd>{key === "SPACE" ? "SPACE" : key}</kbd>
              <span>{KEY_LABELS[key]}</span>
            </div>
          ))}
        </div>

        <div className="teleop-state">
          <dl>
            <div><dt>Keyboard capture</dt><dd>{keyboardCapture ? "ACTIVE" : "OFF"}</dd></div>
            <div><dt>Backend state</dt><dd>{(status.active_keys || []).join(" + ") || "RELEASED"}</dd></div>
            <div><dt>Pi-applied state</dt><dd>{(status.agent_keys || []).join(" + ") || "RELEASED"}</dd></div>
            <div><dt>Round trip</dt><dd>{status.round_trip_ms == null ? "—" : `${status.round_trip_ms} ms`}</dd></div>
            <div><dt>Dead-man</dt><dd>{status.deadman_ms == null ? "—" : `${status.deadman_ms} ms`}</dd></div>
          </dl>

          <div className="teleop-actions">
            {!requested && <button onClick={takeControl} disabled={!token}>Take control lease</button>}
            {requested && !keyboardCapture && (
              <button onClick={enableKeyboard} disabled={!online || !status.controls_enabled}>
                Enable keyboard
              </button>
            )}
            {requested && keyboardCapture && (
              <button className="secondary" onClick={() => releaseLocal("operator_capture_off")}>
                Release all keys
              </button>
            )}
            {requested && <button className="secondary" onClick={releaseControl}>Release control lease</button>}
            {requested && status.emergency_stop && (
              <button onClick={resetEmergencyStop} disabled={!online || !status.agent_online || status.reset_pending}>
                {status.reset_pending ? "Reset pending…" : "Reset emergency stop"}
              </button>
            )}
            {requested && (
              <button className="danger-button" onClick={emergencyStop}>
                Emergency stop
              </button>
            )}
          </div>
        </div>
      </div>

      {error && <p className="teleop-error" role="alert">{error}</p>}
      {!status.feature_enabled && (
        <p className="teleop-warning">Remote teleoperation is disabled by the backend safety switch.</p>
      )}
    </section>
  );
}
