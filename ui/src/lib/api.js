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

export { API_BASE };
