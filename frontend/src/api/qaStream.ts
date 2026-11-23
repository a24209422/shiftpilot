import { ApiError, fetchApi, readApiJson } from "./client";
import { qaProgressStages, type QaAnswer, type QaHistoryItem, type QaMode, type QaProgressEvent, type QaProgressStage, type QaStreamEvent } from "./types";

const path = "/api/qa/ask/stream";
const interrupted = () => new ApiError(0, "QA_STREAM_INTERRUPTED", "連線中斷，未收到完整回答");
type AskBody = { question: string; model: string; mode: QaMode; history?: QaHistoryItem[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasAnswerFields(value: unknown): boolean {
  return isRecord(value) && typeof value.answer === "string" && typeof value.sql === "string"
    && typeof value.model === "string" && typeof value.remote === "boolean" && typeof value.truncated === "boolean"
    && Array.isArray(value.columns) && Array.isArray(value.rows) && value.rows.every(Array.isArray)
    && isRecord(value.window) && typeof value.window.from === "string" && typeof value.window.to === "string";
}

function isStreamEvent(value: unknown): value is QaStreamEvent {
  if (!isRecord(value)) return false;
  switch (value.type) {
    case "accepted":
      return true;
    case "step":
      return typeof value.id === "number" && Number.isSafeInteger(value.id) && value.id > 0
        && qaProgressStages.includes(value.stage as QaProgressStage)
        && (value.state === "running" || value.state === "done" || value.state === "failed");
    case "result":
      return hasAnswerFields(value.answer);
    case "error":
      return typeof value.status === "number" && Number.isInteger(value.status)
        && isRecord(value.error) && typeof value.error.code === "string" && typeof value.error.message === "string";
    default:
      return false;
  }
}

async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<QaStreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let remainder = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      const text = remainder + (done ? decoder.decode() : decoder.decode(value, { stream: true }));
      const lines = text.split("\n");
      remainder = done ? "" : lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event: unknown = JSON.parse(line);
        if (!isStreamEvent(event)) throw interrupted();
        yield event;
      }
      if (done) return;
    }
  } catch {
    throw interrupted();
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function askWithProgress(body: AskBody, onProgress: (event: QaProgressEvent) => void, signal?: AbortSignal): Promise<QaAnswer> {
  const response = await fetchApi("POST", path, body, signal);
  if (!response.ok) {
    await readApiJson(response, path);
    throw interrupted();
  }
  if (!response.body || !response.headers.get("content-type")?.startsWith("application/x-ndjson")) throw interrupted();
  let accepted = false;
  for await (const event of readEvents(response.body)) {
    if (event.type === "accepted") {
      if (accepted) throw interrupted();
      accepted = true;
    } else if (!accepted) {
      throw interrupted();
    }
    if (event.type === "result") return event.answer;
    if (event.type === "error") throw new ApiError(event.status, event.error.code, event.error.message, event.error.details);
    onProgress(event);
  }
  throw interrupted();
}
