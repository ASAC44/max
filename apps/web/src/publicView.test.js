import assert from "node:assert/strict";
import test from "node:test";

import { apiDate, missionActivity } from "./publicView.js";

test("API timestamps without an offset are interpreted as UTC", () => {
  assert.equal(
    apiDate("2026-08-02T13:42:45.063935").getTime(),
    Date.parse("2026-08-02T13:42:45.063935Z"),
  );
});

test("mission activity reflects update freshness", () => {
  const updatedAt = "2026-08-02T13:42:00Z";
  assert.deepEqual(missionActivity(updatedAt, Date.parse("2026-08-02T13:43:00Z")), { label: "In progress", tone: "in-progress" });
  assert.deepEqual(missionActivity(updatedAt, Date.parse("2026-08-02T13:50:00Z")), { label: "Active", tone: "active" });
  assert.deepEqual(missionActivity(updatedAt, Date.parse("2026-08-02T14:00:00Z")), { label: "Waiting", tone: "waiting" });
});
