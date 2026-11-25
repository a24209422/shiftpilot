import { onSessionExpired } from "./client";
import { askWithProgress } from "./qaStream";

const body = { question: "特休", model: "fake", mode: "pipeline" as const };
const answer = {
  ...body, answer: "尚有三天", sql: "", columns: [], rows: [], truncated: false, remote: false,
  window: { from: "2026-01-01", to: "2026-12-31" },
};
const accepted = { type: "accepted" };
const running = { type: "step", id: 1, stage: "query", state: "running" };
const encoder = new TextEncoder();
const ndjson = (...events: unknown[]) => encoder.encode(events.map((event) => JSON.stringify(event) + "\n").join(""));

afterEach(() => vi.unstubAllGlobals());

function fakeStream() {
  let writer!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { writer = controller; } });
  const fetch = vi.fn(async () => new Response(stream, { headers: { "Content-Type": "application/x-ndjson" } }));
  vi.stubGlobal("fetch", fetch);
  return { writer, fetch };
}

test("reports progress before the result and decodes split UTF-8", async () => {
  const { writer, fetch } = fakeStream();
  const progress = vi.fn();
  const result = askWithProgress(body, progress);
  const first = ndjson(accepted, running);
  writer.enqueue(first.slice(0, 7));
  writer.enqueue(first.slice(7));
  await vi.waitFor(() => expect(progress.mock.calls).toEqual([[accepted], [running]]));
  const terminal = ndjson({ type: "step", id: 1, stage: "query", state: "done" }, { type: "result", answer });
  const split = terminal.indexOf(encoder.encode("尚")[0]) + 1;
  writer.enqueue(terminal.slice(0, split));
  writer.enqueue(terminal.slice(split));
  writer.close();
  await expect(result).resolves.toEqual(answer);
  expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/qa/ask/stream", expect.objectContaining({
    method: "POST", credentials: "same-origin", headers: expect.objectContaining({ "X-App-Client": "web" }),
    body: JSON.stringify(body),
  }));
});

test("routes a pre-stream unauthorized response through session expiration", async () => {
  const listener = vi.fn();
  const unsubscribe = onSessionExpired(listener);
  vi.stubGlobal("fetch", async () => Response.json({ error: { code: "UNAUTHENTICATED", message: "請先登入" } }, { status: 401 }));
  try {
    await expect(askWithProgress(body, vi.fn())).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(listener).toHaveBeenCalledTimes(1);
  } finally {
    unsubscribe();
  }
});

test.each(["early EOF", "invalid event", "read error"])("fails an interrupted stream with %s", async (failure) => {
  const { writer } = fakeStream();
  const result = expect(askWithProgress(body, vi.fn())).rejects.toMatchObject({ code: "QA_STREAM_INTERRUPTED" });
  writer.enqueue(ndjson(accepted));
  if (failure === "read error") writer.error(new Error("reset"));
  else {
    if (failure === "invalid event") writer.enqueue(ndjson({ ...running, stage: "unknown" }));
    writer.close();
  }
  await result;
});

test("keeps the terminal error details available to the panel", async () => {
  const { writer } = fakeStream();
  const error = { code: "QA_QUERY_FAILED", message: "查詢失敗", details: { sql: "SELECT 1" } };
  const result = expect(askWithProgress(body, vi.fn())).rejects.toMatchObject({ status: 422, ...error });
  writer.enqueue(ndjson(accepted, { type: "error", status: 422, error }));
  writer.close();
  await result;
});
