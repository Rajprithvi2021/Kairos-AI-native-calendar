// Thin typed client. All calls go to /api/* on this origin; next.config.ts proxies them to FastAPI.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function participant(): string | null {
  try {
    return window.localStorage.getItem("kairos.participant");
  } catch {
    return null;
  }
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body && !isForm ? { "Content-Type": "application/json" } : undefined,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail || `Request failed (${res.status})`);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form, true),
};

export function sendFeedback(targetType: string, targetId: string, rating: 1 | -1, reasons: string[] = []) {
  return api.post("/api/feedback", { target_type: targetType, target_id: targetId, rating, reasons, participant_id: participant() });
}

export function track(name: string, props: Record<string, unknown> = {}) {
  return api.post("/api/telemetry", { name, props, participant_id: participant() }).catch(() => undefined);
}
