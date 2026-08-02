const HAS_TIMEZONE = /(Z|[+-]\d{2}:\d{2})$/;

export const apiDate = (value) => {
  const timestamp = String(value || "");
  return new Date(HAS_TIMEZONE.test(timestamp) ? timestamp : `${timestamp}Z`);
};

export const missionActivity = (updatedAt, now = Date.now()) => {
  const ageMs = now - apiDate(updatedAt).getTime();
  if (!Number.isFinite(ageMs) || ageMs < 0) return { label: "Active", tone: "active" };
  if (ageMs <= 2 * 60_000) return { label: "In progress", tone: "in-progress" };
  if (ageMs <= 15 * 60_000) return { label: "Active", tone: "active" };
  return { label: "Waiting", tone: "waiting" };
};
