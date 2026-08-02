export const TELEOP_PROTOCOL_VERSION = 1;

export const KEY_BY_CODE = Object.freeze({
  KeyW: "W",
  KeyA: "A",
  KeyS: "S",
  KeyD: "D",
  Space: "SPACE",
  Digit1: "1",
  Digit2: "2",
  Digit3: "3",
  Digit4: "4",
  Digit5: "5",
});

export const KEY_LABELS = Object.freeze({
  W: "Forward",
  A: "Left",
  S: "Reverse",
  D: "Right",
  SPACE: "Horn",
  1: "Drive 30%",
  2: "Drive 60%",
  3: "Drive 100%",
  4: "Speaker 150%",
  5: "Speaker 200%",
});

export const MOVEMENT_OPPOSITES = Object.freeze([
  ["W", "S"],
  ["A", "D"],
]);

export const DRIVE_MODES = Object.freeze(["1", "2", "3"]);
export const AUDIO_MODES = Object.freeze(["4", "5"]);

export const websocketUrl = (api) => {
  const url = new URL(api, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/teleop/ws/controller";
  url.search = "";
  url.hash = "";
  return url.toString();
};

export const inputMessage = (sequence, keys) => ({
  type: "input",
  protocol_version: TELEOP_PROTOCOL_VERSION,
  sequence,
  sent_at_ms: Date.now(),
  keys: [...keys].sort(),
});

export const simpleMessage = (type) => ({
  type,
  protocol_version: TELEOP_PROTOCOL_VERSION,
});

export const isEditableTarget = (target) => (
  target instanceof HTMLInputElement
  || target instanceof HTMLTextAreaElement
  || target instanceof HTMLSelectElement
  || target?.isContentEditable
);
