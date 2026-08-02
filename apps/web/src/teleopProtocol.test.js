import assert from "node:assert/strict";
import test from "node:test";

import {
  AUDIO_MODES,
  DRIVE_MODES,
  KEY_BY_CODE,
  KEY_LABELS,
  TELEOP_PROTOCOL_VERSION,
  inputMessage,
} from "./teleopProtocol.js";

test("all requested physical keys have a bounded target action", () => {
  assert.deepEqual(
    Object.keys(KEY_BY_CODE).sort(),
    ["Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "KeyA", "KeyD", "KeyS", "KeyW", "Space"],
  );
  assert.deepEqual(
    [...new Set(Object.values(KEY_BY_CODE))].sort(),
    ["1", "2", "3", "4", "5", "A", "D", "S", "SPACE", "W"],
  );
  for (const key of Object.values(KEY_BY_CODE)) assert.ok(KEY_LABELS[key]);
  assert.deepEqual(DRIVE_MODES, ["1", "2", "3"]);
  assert.deepEqual(AUDIO_MODES, ["4", "5"]);
});

test("input messages are complete state snapshots with monotonically supplied sequence", () => {
  const message = inputMessage(42, new Set(["W", "A", "SPACE"]));
  assert.equal(message.type, "input");
  assert.equal(message.protocol_version, TELEOP_PROTOCOL_VERSION);
  assert.equal(message.sequence, 42);
  assert.deepEqual(message.keys, ["A", "SPACE", "W"]);
  assert.ok(Number.isInteger(message.sent_at_ms));
});
