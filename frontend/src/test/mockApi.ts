import { afterEach } from "vitest";

export interface MockRequest { body: unknown; params: URLSearchParams }
export interface MockResponse { status?: number; body?: unknown }
export type MockRoutes = Record<string, (request: MockRequest) => MockResponse | Promise<MockResponse>>;
export interface MockCall { method: string; path: string; params: URLSearchParams; body: unknown; headers: Headers }

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

// 只給測試用：把 fetch 換成依「METHOD /path」查表的假後端。沒登記的路由回 404，並讓呼叫端看到錯誤
export function mockApi(routes: MockRoutes): { calls: MockCall[]; routes: MockRoutes } {
  const calls: MockCall[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: url.pathname, params: url.searchParams, body, headers });
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) {
      return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `沒有登記的測試路由：${method} ${url.pathname}`, details: null } }), {
        status: 404, headers: { "Content-Type": "application/json" },
      });
    }
    const result = await handler({ body, params: url.searchParams });
    const status = result.status ?? 200;
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(result.body ?? null), { status, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  return { calls, routes };
}
