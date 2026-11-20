export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Params = Record<string, string | number | boolean | undefined>;
const expiredListeners = new Set<() => void>();

export function onSessionExpired(listener: () => void): () => void {
  expiredListeners.add(listener);
  return () => { expiredListeners.delete(listener); };
}

const networkError = (status: number) => new ApiError(status, "NETWORK", "連不上伺服器，請確認後端有在執行");

async function request<T>(method: string, path: string, params?: Params, body?: unknown): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined) query.set(key, String(value));
  }
  const url = query.size ? `${path}?${query}` : path;
  const headers: Record<string, string> = { "X-App-Client": "web" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(url, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw networkError(0);
  }
  if (response.status === 204) return undefined as T;
  let data: any;
  try {
    data = await response.json();
  } catch {
    // 不是 JSON：多半是後端沒開、代理回了 HTML 錯誤頁
    throw networkError(response.status);
  }
  if (!response.ok) {
    const error = data?.error;
    if (!error) throw networkError(response.status);
    // 登入本身的 401 是「密碼錯」，不是「登入過期」
    if (response.status === 401 && error.code === "UNAUTHENTICATED" && path !== "/api/auth/login") {
      expiredListeners.forEach((listener) => listener());
    }
    throw new ApiError(response.status, error.code, error.message, error.details ?? null);
  }
  return data as T;
}

export const apiGet = <T>(path: string, params?: Params) => request<T>("GET", path, params);
export const apiSend = <T = void>(method: "POST" | "PATCH" | "PUT" | "DELETE", path: string, body?: unknown) =>
  request<T>(method, path, undefined, body);
