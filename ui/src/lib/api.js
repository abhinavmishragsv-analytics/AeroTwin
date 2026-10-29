/**
 * API base + airport slug resolution.
 *
 * The URL path segment (e.g. /delhi, /mumbai) selects which airport twin this
 * page connects to. An empty path falls back to the server's default (VABO).
 * This is the entire mechanism behind "switch airport from the URL" - no
 * routing library, no rebuild, just reading location.pathname once.
 */
const HOST = window.location.hostname;
const API_BASE = import.meta.env.VITE_API_BASE || `http://${HOST}:8000`;
const WS_BASE = API_BASE.replace(/^http/, "ws");

/**
 * A fresh id for this page load. Not persisted anywhere on purpose: the
 * server keys simulations by it, so a reload produces a new id, and therefore
 * a brand new simulation starting at T+0. Keeping it in sessionStorage would
 * make a reload rejoin the old, already-running simulation - which is exactly
 * the behaviour being fixed.
 */
export const SESSION_ID =
  (crypto.randomUUID && crypto.randomUUID()) ||
  `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

export function slugFromPath() {
  const seg = window.location.pathname.split("/").filter(Boolean)[0];
  return seg || null;
}

/** True on /<airport>/telemetry. No router library: the app has two pages. */
export function isTelemetryPath() {
  return window.location.pathname.split("/").filter(Boolean)[1] === "telemetry";
}

export async function fetchAirports() {
  const res = await fetch(`${API_BASE}/api/airports`);
  if (!res.ok) throw new Error(`GET /api/airports failed: ${res.status}`);
  return res.json();
}

export async function fetchLayout(identifier) {
  const res = await fetch(`${API_BASE}/api/airports/${identifier}/layout`);
  if (!res.ok) throw new Error(`GET layout failed: ${res.status}`);
  return res.json();
}

export async function postDisruption(identifier, body) {
  const res = await fetch(`${API_BASE}/api/airports/${identifier}/disrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, session: SESSION_ID }),
  });
  if (!res.ok) throw new Error(`disrupt failed: ${res.status}`);
  return res.json();
}

export function twinSocketUrl(identifier) {
  return `${WS_BASE}/ws/twin/${identifier}?session=${encodeURIComponent(SESSION_ID)}`;
}

/** Path of the telemetry page for an airport. Passing the session id is what
 *  lets the new tab read the SAME simulation this tab is showing - twins are
 *  per-session (see core/main.py TwinRegistry), so without it the telemetry
 *  page would look at a different, empty airport. */
export function telemetryUrl(slug, { leg } = {}) {
  const q = new URLSearchParams({ session: SESSION_ID });
  if (leg) q.set("leg", leg);
  return `/${slug}/telemetry?${q.toString()}`;
}

export function openTelemetry(slug, opts) {
  window.open(telemetryUrl(slug, opts), "_blank", "noopener");
}

export async function fetchTelemetryLegs(identifier, session, direction, state = "all") {
  const q = new URLSearchParams({ state });
  if (session) q.set("session", session);
  if (direction) q.set("direction", direction);
  const res = await fetch(`${API_BASE}/api/airports/${identifier}/telemetry/legs?${q}`);
  if (!res.ok) throw new Error(res.status === 404 ? "session_not_found" : `telemetry legs failed: ${res.status}`);
  return res.json();
}

export async function fetchTelemetryLeg(identifier, session, legId) {
  const q = new URLSearchParams();
  if (session) q.set("session", session);
  const res = await fetch(`${API_BASE}/api/airports/${identifier}/telemetry/legs/${encodeURIComponent(legId)}?${q}`);
  if (!res.ok) throw new Error(`telemetry leg failed: ${res.status}`);
  return res.json();
}

export async function fetchTelemetrySchema() {
  const res = await fetch(`${API_BASE}/api/telemetry/schema`);
  if (!res.ok) throw new Error(`telemetry schema failed: ${res.status}`);
  return res.json();
}

export function telemetrySocketUrl(identifier, session) {
  const q = session ? `?session=${encodeURIComponent(session)}` : "";
  return `${WS_BASE}/ws/telemetry/${identifier}${q}`;
}

export function sessionFromQuery() {
  return new URLSearchParams(window.location.search).get("session");
}

export { API_BASE };
