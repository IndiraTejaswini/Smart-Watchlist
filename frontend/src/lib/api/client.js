import { API_BASE, USE_MOCK } from "../env.js";
import { handleMock } from "../mock/index.js";

/**
 * client.js — the single door to the API.
 *
 * Errors are RFC 7807 (§16), so a failed request carries a `title` and a
 * `detail` the interface can show verbatim rather than a generic "Something
 * went wrong". R5: when data is missing the UI says so in plain English, which
 * it can only do if the error survives the transport layer intact — so a real
 * backend failure is never silently swapped for a mock response. USE_MOCK is
 * a deliberate, explicit transport choice (env.js), not a fallback triggered
 * by failure.
 */

export class ApiError extends Error {
  /** @param {{status:number,title:string,detail?:string,type?:string}} problem */
  constructor(problem) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.title = problem.title;
    this.detail = problem.detail;
    this.type = problem.type;
  }
}

/**
 * @param {string} path e.g. "/brief?watchlist_id=wl_1"
 * @param {object} [options]
 * @param {"GET"|"POST"|"PATCH"|"DELETE"} [options.method]
 * @param {unknown} [options.body]
 * @param {{parse:(v:unknown)=>unknown}} [options.schema] Zod schema, boundary only
 * @param {AbortSignal} [options.signal]
 */
export async function apiFetch(path, options = {}) {
  const { method = "GET", body, schema, signal } = options;

  const payload = USE_MOCK
    ? await handleMock(method, path, body)
    : await realFetch(path, method, body, signal);

  // Zod runs at the boundary and only at the boundary (R8). A payload that does
  // not match the contract is a bug worth surfacing loudly in development
  // rather than a set of `undefined`s that render as blank cells.
  return schema ? schema.parse(payload) : payload;
}

async function realFetch(path, method, body, signal) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    signal,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  if (!response.ok) {
    let problem = {
      status: response.status,
      title: `Request failed with status ${response.status}`,
    };
    try {
      const parsed = await response.json();
      problem = { ...problem, ...parsed, status: parsed.status ?? response.status };
    } catch {
      // A non-JSON error body is itself the whole story; keep the status line.
    }
    throw new ApiError(problem);
  }

  if (response.status === 204) return null;
  return response.json();
}
