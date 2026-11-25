import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QaAnswer, QaIntent, QaModel, QaProposal } from "../api/types";
import type { MockRoutes } from "../test/mockApi";
import { renderApp } from "../test/renderApp";
import { previousTurnFor, toHistory, type ChatEntry } from "./QaMessage";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 22, 9, 30));
});
afterEach(() => {
  vi.useRealTimers();
  // 開發者模式記在 localStorage，不清掉會漏到下一個測試
  localStorage.clear();
});

const models: QaModel[] = [
  { id: "qwen2.5:3b", label: "qwen2.5:3b（本機）", remote: false },
  { id: "gemini-x", label: "gemini-x（Google）", remote: true },
];
const answer: QaAnswer = {
  answer: "黃志強明天上晚班，14:00 到 23:00。", sql: "SELECT shift_name FROM day_shifts", columns: ["shift_name", "start_at"],
  rows: [["晚班", "2026-11-23T14:00:00"]], truncated: false, model: "qwen2.5:3b", remote: false, mode: "pipeline",
  window: { from: "2026-08-23", to: "2027-02-20" },
};

const panel = () => screen.getByRole("complementary", { name: "問答面板" });
const devRoute = "/?dev=1";
// 外殼要等登入狀態與權限載入完才會畫出面板，所以先等面板出現再回傳
const open = async (routes: MockRoutes = {}, permissions = ["qa.ask"], route = "/") => {
  const view = renderApp({ route, permissions, routes: { "GET /api/qa/models": () => ({ body: models }), ...routes } });
  await screen.findByRole("complementary", { name: "問答面板" });
  return view;
};

test("testModelsComeFromApi", async () => {
  await open();
  const select = await within(panel()).findByRole("combobox", { name: "模型" });
  await waitFor(() => expect(Array.from(select.querySelectorAll("option")).map((item) => item.value)).toEqual(["qwen2.5:3b", "gemini-x"]));
  expect(select).toHaveValue("qwen2.5:3b");
});

test("testRemoteModelShowsWarning", async () => {
  await open();
  const select = await within(panel()).findByRole("combobox", { name: "模型" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  await userEvent.setup().selectOptions(select, "gemini-x");
  expect(within(panel()).getByText("問題與查詢結果會送到雲端廠商")).toBeInTheDocument();
});

test("testAskShowsAnswerTableAndSql", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: answer }) });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "黃志強明天上什麼班？");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("黃志強明天上晚班，14:00 到 23:00。")).toBeInTheDocument();
  expect(within(panel()).getByText("黃志強明天上什麼班？", { selector: ".bubble" })).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/qa/ask/stream")?.body).toEqual({ question: "黃志強明天上什麼班？", model: "qwen2.5:3b", mode: "assistant-jev", history: [] });
  await user.click(within(panel()).getByText("看查詢結果"));
  expect(within(panel()).getByRole("cell", { name: "晚班" })).toBeInTheDocument();
  expect(within(panel()).getByText("SELECT shift_name FROM day_shifts")).toBeInTheDocument();
  expect(within(panel()).getByText("資料範圍：8/23（日） ～ 2/20（六）")).toBeInTheDocument();
  expect(within(panel()).getByRole("textbox", { name: "問題" })).toHaveValue("");
});

test("testRemoteAnswerIsMarked", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, model: "gemini-x", remote: true } }) });
  const user = userEvent.setup();
  const select = await within(panel()).findByRole("combobox", { name: "模型" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  await user.selectOptions(select, "gemini-x");
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("gemini-x・已送到雲端")).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/qa/ask/stream")?.body).toEqual({ question: "問題", model: "gemini-x", mode: "assistant-jev", history: [] });
});

test("testPendingShownWhileWaitingAndDoubleSubmitSendsOnce", async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const { api } = await open({ "POST /api/qa/ask/stream": async () => { await gate; return { body: answer }; } });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  const input = within(panel()).getByRole("textbox", { name: "問題" });
  await user.type(input, "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("思考中")).toBeInTheDocument();
  await user.type(input, "再問一次{Enter}");
  expect(api.calls.filter((call) => call.path === "/api/qa/ask/stream")).toHaveLength(1);
  release();
  expect(await within(panel()).findByText("黃志強明天上晚班，14:00 到 23:00。")).toBeInTheDocument();
  expect(within(panel()).queryByText("思考中")).toBeNull();
});

test("testTruncatedNoteShowsRowCount", async () => {
  await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, truncated: true } }) });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await user.click(await within(panel()).findByText("看查詢結果"));
  expect(within(panel()).getByText("只顯示前 1 筆")).toBeInTheDocument();
});

function controlledProgress() {
  let writer!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { writer = controller; } });
  const push = (...events: unknown[]) => writer.enqueue(new TextEncoder().encode(events.map((event) => JSON.stringify(event) + "\n").join("")));
  return { stream, push, close: () => writer.close() };
}

test("shows real progress before the answer and retains failed attempts", async () => {
  const progress = controlledProgress();
  await open({ "POST /api/qa/ask/stream": () => ({ stream: progress.stream }) });
  const user = userEvent.setup();
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題{Enter}");
  expect(await within(panel()).findByText("正在送出")).toBeVisible();
  const query = { type: "step", stage: "query" };
  progress.push({ type: "accepted" }, { ...query, id: 1, state: "running" });
  expect(await within(panel()).findByText("查詢資料")).toBeVisible();
  expect(within(panel()).getByText("進行中")).toBeVisible();
  expect(within(panel()).queryByText(answer.answer)).toBeNull();
  progress.push({ ...query, id: 1, state: "failed" }, { ...query, id: 2, state: "running" },
    { ...query, id: 2, state: "done" }, { type: "result", answer });
  progress.close();
  expect(await within(panel()).findByText(answer.answer)).toBeVisible();
  await user.click(within(panel()).getByText("查看處理進度"));
  expect(within(panel()).getByText("失敗")).toBeVisible();
  expect(within(panel()).getByText("已完成")).toBeVisible();
  expect(within(panel()).queryByText("進行中")).toBeNull();
});

test("shows the intent step and readable tool names", async () => {
  const progress = controlledProgress();
  await open({ "POST /api/qa/ask/stream": () => ({ stream: progress.stream }) });
  const user = userEvent.setup();
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題{Enter}");
  progress.push({ type: "accepted" }, { type: "step", stage: "intent", id: 1, state: "running" });
  expect(await within(panel()).findByText("判斷要辦的事")).toBeVisible();
  progress.push(
    { type: "step", stage: "intent", id: 1, state: "done" },
    { type: "step", stage: "tool", id: 2, state: "running", tool: "find_available_resources" },
  );
  expect(await within(panel()).findByText("找可用的會議室")).toBeVisible();
  // 沒列在對照表裡的新工具直接顯示原名，不會變成空白
  progress.push({ type: "step", stage: "tool", id: 3, state: "running", tool: "brand_new_tool" });
  expect(await within(panel()).findByText("brand_new_tool")).toBeVisible();
  progress.push({ type: "result", answer });
  progress.close();
  expect(await within(panel()).findByText(answer.answer)).toBeVisible();
});

test("an interrupted question stops spinning and the next question starts fresh", async () => {
  const progress = controlledProgress();
  let count = 0;
  await open({ "POST /api/qa/ask/stream": () => count++ === 0 ? { stream: progress.stream } : { body: answer } });
  const user = userEvent.setup();
  const input = within(panel()).getByRole("textbox", { name: "問題" });
  await user.type(input, "問題{Enter}");
  progress.push({ type: "accepted" }, { type: "step", stage: "model", id: 1, state: "running" });
  expect(await within(panel()).findByText("等待模型回應")).toBeVisible();
  progress.close();
  expect(await within(panel()).findByRole("alert")).toHaveTextContent("連線中斷，未收到完整回答");
  expect(within(panel()).getByText("狀態未確認")).toBeVisible();
  await user.type(input, "下一題{Enter}");
  expect(await within(panel()).findByText(answer.answer)).toBeVisible();
  expect(within(panel()).getAllByText("等待模型回應")).toHaveLength(1);
});

test("scrolls the chat to a newly submitted question and respects scrolling back", async () => {
  const progress = controlledProgress();
  await open({ "POST /api/qa/ask/stream": () => ({ stream: progress.stream }) });
  const chatLog = within(panel()).getByRole("log");
  Object.defineProperties(chatLog, { scrollHeight: { value: 600 }, clientHeight: { value: 200 } });
  chatLog.scrollTop = 40;
  fireEvent.scroll(chatLog);
  await userEvent.setup().type(within(panel()).getByRole("textbox", { name: "問題" }), "問題{Enter}");
  expect(chatLog.scrollTop).toBeGreaterThanOrEqual(400);
  chatLog.scrollTop = 40;
  fireEvent.scroll(chatLog);
  progress.push({ type: "accepted" }, { type: "step", stage: "model", id: 1, state: "running" });
  expect(await within(panel()).findByText("等待模型回應")).toBeVisible();
  expect(chatLog.scrollTop).toBe(40);
  progress.close();
  await within(panel()).findByRole("alert");
});

test("testNonApiErrorShowsFallbackMessage", async () => {
  await open({ "POST /api/qa/ask/stream": () => { throw new Error("boom"); } });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByRole("alert")).toBeInTheDocument();
  expect(within(panel()).getByRole("alert")).toHaveTextContent(/連不上伺服器|問答失敗，請再試一次/);
});

test("testEmptyModelListShowsNoteAndDisablesSend", async () => {
  await open({ "GET /api/qa/models": () => ({ body: [] }) });
  expect(await within(panel()).findByText("目前沒有可用的模型")).toBeInTheDocument();
  await userEvent.setup().type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  expect(within(panel()).getByRole("button", { name: "送出" })).toBeDisabled();
});

test("testDuplicateColumnNamesRenderWithoutKeyWarning", async () => {
  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, columns: ["name", "name"], rows: [["甲", { a: 1 }]] } }) });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await user.click(await within(panel()).findByText("看查詢結果"));
  expect(within(panel()).getAllByRole("columnheader", { name: "name" })).toHaveLength(2);
  expect(within(panel()).getByRole("cell", { name: '{"a":1}' })).toBeInTheDocument();
  expect(spy.mock.calls.some((call) => String(call[0]).includes("key"))).toBe(false);
  spy.mockRestore();
});

test("testErrorShowsMessageAndSql", async () => {
  await open({ "POST /api/qa/ask/stream": () => ({ status: 422, body: { error: { code: "QA_QUERY_FAILED", message: "查詢失敗：欄位不存在", details: { sql: "SELECT nope", error: "欄位不存在" } } } }) });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("查詢失敗：欄位不存在")).toBeInTheDocument();
  await user.click(within(panel()).getByText("看 SQL"));
  expect(within(panel()).getByText("SELECT nope")).toBeInTheDocument();
});

test("testWithoutPermissionShowsNoticeAndDoesNotLoadModels", async () => {
  const { api } = await open({}, []);
  expect(await within(panel()).findByText("沒有使用問答的權限")).toBeInTheDocument();
  expect(api.calls.some((call) => call.path === "/api/qa/models")).toBe(false);
});

test("testDefaultWindowNoteBeforeAsking", async () => {
  await open();
  expect(await within(panel()).findByText("資料範圍：8/24（一） ～ 2/20（六）")).toBeInTheDocument();
});

test("testCollapseAndExpand", async () => {
  await open();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "收合問答面板" }));
  expect(panel()).toHaveClass("collapsed");
  await user.click(screen.getByRole("button", { name: "展開問答面板" }));
  expect(panel()).not.toHaveClass("collapsed");
});

test("testKeyboardResizeIsClampedAndResettable", async () => {
  await open();
  const handle = await screen.findByRole("separator", { name: "調整問答面板寬度" });
  expect(handle).toHaveAttribute("aria-valuenow", "400");
  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(handle).toHaveAttribute("aria-valuenow", "424");
  for (let index = 0; index < 20; index += 1) fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(handle).toHaveAttribute("aria-valuenow", "320");
  fireEvent.keyDown(handle, { key: "Home" });
  expect(handle).toHaveAttribute("aria-valuenow", "400");
});

test("testDragWidensPanel", async () => {
  await open();
  const handle = await screen.findByRole("separator", { name: "調整問答面板寬度" });
  fireEvent.pointerDown(handle, { clientX: 1000 });
  fireEvent.pointerMove(window, { clientX: 950 });
  fireEvent.pointerUp(window);
  expect(handle).toHaveAttribute("aria-valuenow", "450");
});

const askQuestion = async (text = "下週二下午誰有空？") => {
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), text);
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  return user;
};

test("testModeIsSentWithQuestion", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: answer }) }, undefined, devRoute);
  const user = userEvent.setup();
  const mode = await within(panel()).findByRole("combobox", { name: "模式" });
  expect(mode).toHaveValue("assistant-jev");
  await user.selectOptions(mode, "agent");
  await askQuestion();
  await within(panel()).findByText(answer.answer);
  expect(api.calls.find((call) => call.path === "/api/qa/ask/stream")?.body).toEqual({ question: "下週二下午誰有空？", model: "qwen2.5:3b", mode: "agent" });
});

test("testAgentStepsAreListed", async () => {
  const steps = [
    { tool: "find_available_people", arguments: { start: "2026-11-24 14:00", end: "2026-11-24 15:00", department: "工程部" }, rowCount: 3, error: null },
    { tool: "run_sql", arguments: { sql: "SELECT nope" }, rowCount: null, error: "欄位不存在" },
  ];
  await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, mode: "agent", steps } }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("find_available_people（2026-11-24 14:00，2026-11-24 15:00，工程部）→ 3 筆")).toBeInTheDocument();
  expect(within(panel()).getByText("run_sql（SELECT nope）→ 失敗：欄位不存在")).toBeInTheDocument();
});

test("testEmptySqlIsHidden", async () => {
  const { container } = await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, sql: "", mode: "agent", steps: [] } }) });
  await askQuestion();
  await within(panel()).findByText(answer.answer);
  expect(container.querySelector(".qaSql")).toBeNull();
  expect(within(panel()).queryByText("看工具步驟")).toBeNull();
});

const jevSteps = [{ tool: "find_available_people", arguments: { start: "2026-11-24 14:00", end: "2026-11-24 15:00" }, rowCount: 3, error: null }];

test("testJevModeIsSent", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: answer }) }, undefined, devRoute);
  const user = userEvent.setup();
  const mode = await within(panel()).findByRole("combobox", { name: "模式" });
  await user.selectOptions(mode, "jev");
  await askQuestion();
  await within(panel()).findByText(answer.answer);
  expect(api.calls.find((call) => call.path === "/api/qa/ask/stream")?.body).toEqual({ question: "下週二下午誰有空？", model: "qwen2.5:3b", mode: "jev" });
});

test("testJevRouteIsShown", async () => {
  const route = { tool: "find_available_people", confidence: 0.923, fallbackReason: null, promptTokens: 439, seconds: 0.2 };
  await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, mode: "jev", steps: jevSteps, route } }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("Jev 選了 find_available_people（信心 0.92）")).toBeInTheDocument();
});

test("testJevFallbackShowsReason", async () => {
  const route = { tool: null, confidence: 0.3, fallbackReason: "low_confidence", promptTokens: 439, seconds: 0.2 };
  await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, mode: "jev", steps: jevSteps, route } }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("Jev 沒選定（信心不足），三個工具都給")).toBeInTheDocument();
});

test("testJevRouteShownEvenWithoutSteps", async () => {
  const route = { tool: null, confidence: null, fallbackReason: "unavailable", promptTokens: null, seconds: 10 };
  await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, mode: "jev", steps: [], route } }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("Jev 沒選定（呼叫失敗），三個工具都給")).toBeInTheDocument();
});

const askBodies = (api: { calls: { path: string; body?: unknown }[] }) => api.calls.filter((call) => call.path === "/api/qa/ask/stream").map((call) => call.body as Record<string, unknown>);

test("testToHistoryMapsAndTrims", () => {
  const entries: ChatEntry[] = [];
  for (let index = 0; index < 45; index += 1) {
    entries.push({ id: index * 2, kind: "question", text: `問${index}` });
    entries.push({ id: index * 2 + 1, kind: "answer", result: { ...answer, answer: `答${index}` } });
  }
  entries.push({ id: 100, kind: "note", text: "（系統紀錄）已建立" });
  entries.push({ id: 101, kind: "error", message: "壞了", sql: null });
  entries.push({ id: 102, kind: "pending", progress: { startedAt: 0, accepted: false, steps: [] } });
  const history = toHistory(entries);
  expect(history).toHaveLength(40);
  expect(history[history.length - 1]).toEqual({ role: "user", content: "（系統紀錄）已建立" });
  expect(history.every((item) => Object.keys(item).sort().join() === "content,role")).toBe(true);
  expect(history.some((item) => item.content === "壞了")).toBe(false);
  expect(toHistory([{ id: 1, kind: "question", text: "長".repeat(1200) }])[0].content).toHaveLength(1000);
});

test("testToHistoryIncludesProposalSummary", () => {
  const proposal: QaProposal = {
    kind: "booking.create",
    request: { method: "POST", path: "/api/booking/bookings", body: {} },
    summary: [{ label: "標題", value: "週會" }, { label: "會議室", value: "A 會議室" }],
    quote: null,
  };
  const history = toHistory([{ id: 1, kind: "answer", result: { ...answer, answer: "請確認。", proposal } }]);
  expect(history).toEqual([{ role: "assistant", content: "請確認。\n（提議：標題=週會；會議室=A 會議室）" }]);
  const long = toHistory([{ id: 2, kind: "answer", result: { ...answer, answer: "長".repeat(990), proposal } }]);
  expect(long[0].content).toHaveLength(1000);
});

test("testAssistantSendsHistory", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, mode: "assistant", proposal: null } }) }, undefined, devRoute);
  const user = userEvent.setup();
  await user.selectOptions(await within(panel()).findByRole("combobox", { name: "模式" }), "assistant");
  await askQuestion("第一題");
  await within(panel()).findByText(answer.answer);
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "第二題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await waitFor(() => expect(askBodies(api)).toHaveLength(2));
  expect(askBodies(api)[0]).toEqual({ question: "第一題", model: "qwen2.5:3b", mode: "assistant", history: [] });
  expect(askBodies(api)[1].history).toEqual([{ role: "user", content: "第一題" }, { role: "assistant", content: answer.answer }]);
});

test("testAgentModeSendsNoHistory", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: answer }) }, undefined, devRoute);
  const user = userEvent.setup();
  await user.selectOptions(await within(panel()).findByRole("combobox", { name: "模式" }), "agent");
  await askQuestion("第一題");
  await within(panel()).findByText(answer.answer);
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "第二題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await waitFor(() => expect(askBodies(api)).toHaveLength(2));
  expect(askBodies(api)[1]).not.toHaveProperty("history");
});

test("testClearConversation", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: { ...answer, mode: "assistant", proposal: null } }) }, undefined, devRoute);
  const user = userEvent.setup();
  await user.selectOptions(await within(panel()).findByRole("combobox", { name: "模式" }), "assistant");
  await askQuestion("第一題");
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByRole("button", { name: "清除對話" }));
  expect(within(panel()).queryByText("第一題", { selector: ".bubble" })).toBeNull();
  expect(within(panel()).queryByText(answer.answer)).toBeNull();
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "第二題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await waitFor(() => expect(askBodies(api)).toHaveLength(2));
  expect(askBodies(api)[1].history).toEqual([]);
});

const bookingIntent: QaIntent = { name: "booking", confidence: 0.923, fallbackReason: null, reused: false, promptTokens: 300, seconds: 0.1 };
const intentAnswer = (overrides: Partial<QaAnswer> = {}): QaAnswer => (
  { ...answer, rows: [], columns: [], mode: "assistant-jev", proposal: null, intent: bookingIntent, ...overrides }
);
const openProposal: QaProposal = {
  kind: "booking.create", request: { method: "POST", path: "/api/booking/bookings", body: {} }, summary: [], quote: null,
};

test("testPreviousIntentAfterClarifyingReply", () => {
  const entries: ChatEntry[] = [{ id: 1, kind: "question", text: "幫我約會議" }, { id: 2, kind: "answer", result: intentAnswer() }];
  expect(previousTurnFor(entries)).toEqual({ intent: "booking", openProposal: null });
});

test("testPreviousIntentAfterOpenProposal", () => {
  const entries: ChatEntry[] = [{ id: 1, kind: "answer", result: intentAnswer({ rows: [["x"]], columns: ["c"], proposal: openProposal }) }];
  expect(previousTurnFor(entries)).toEqual({ intent: null, openProposal: "booking" });
});

test("testOpenProposalIntentComesFromProposalKind", () => {
  // 上一輪合併過工具組時，以卡片本身是哪種提議為準
  const leaveProposal: QaProposal = { ...openProposal, kind: "leave.create" };
  const merged: QaIntent = { ...bookingIntent, reused: true, addedName: "leave" };
  const entries: ChatEntry[] = [{ id: 1, kind: "answer", result: intentAnswer({ intent: merged, proposal: leaveProposal }) }];
  expect(previousTurnFor(entries)).toEqual({ intent: null, openProposal: "leave" });
});

test("testClarifyingAfterMergeReusesAddedIntent", () => {
  const merged: QaIntent = { ...bookingIntent, reused: true, addedName: "manageBooking" };
  expect(previousTurnFor([{ id: 1, kind: "answer", result: intentAnswer({ intent: merged }) }])).toEqual({ intent: "manageBooking", openProposal: null });
});

test("testNoPreviousIntentWhenNotConfigured", () => {
  // 沒設 key 時不沿用，讓後端每一則都標出「沒設定 Jev」
  const notConfigured: QaIntent = { name: null, confidence: null, fallbackReason: "not_configured", reused: false, promptTokens: null, seconds: 0 };
  expect(previousTurnFor([{ id: 1, kind: "answer", result: intentAnswer({ intent: notConfigured }) }])).toBeNull();
});

test("testNoPreviousIntentAfterNote", () => {
  // 確認或取消確認卡後會補一則系統紀錄
  const entries: ChatEntry[] = [
    { id: 1, kind: "answer", result: intentAnswer({ proposal: openProposal }) },
    { id: 2, kind: "note", text: "（系統紀錄）使用者取消了這個提議" },
  ];
  expect(previousTurnFor(entries)).toBeNull();
});

test("testNoPreviousIntentAfterTable", () => {
  expect(previousTurnFor([{ id: 1, kind: "answer", result: intentAnswer({ rows: [["晚班"]], columns: ["shift"] }) }])).toBeNull();
  expect(previousTurnFor([])).toBeNull();
  // 沒有 intent 的回覆（其他模式）不沿用
  expect(previousTurnFor([{ id: 1, kind: "answer", result: intentAnswer({ intent: undefined }) }])).toBeNull();
});

test("testPreviousIntentAllWhenFallback", () => {
  const fallback: QaIntent = { name: null, confidence: 0.3, fallbackReason: "low_confidence", reused: false, promptTokens: 300, seconds: 0.1 };
  expect(previousTurnFor([{ id: 1, kind: "answer", result: intentAnswer({ intent: fallback }) }])).toEqual({ intent: "all", openProposal: null });
});

async function shownIntentText(intent: QaIntent) {
  await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer({ steps: [], intent }) }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
}

test("testIntentIsShown", async () => {
  await shownIntentText(bookingIntent);
  expect(within(panel()).getByText("Jev 判斷：預約會議（信心 0.92）")).toBeInTheDocument();
});

test("testIntentNotConfiguredIsShown", async () => {
  await shownIntentText({ name: null, confidence: null, fallbackReason: "not_configured", reused: false, promptTokens: null, seconds: 0 });
  expect(within(panel()).getByText("沒設定 Jev，9 個工具都給")).toBeInTheDocument();
});

test("testIntentFallbackIsShown", async () => {
  await shownIntentText({ name: null, confidence: 0.3, fallbackReason: "low_confidence", reused: false, promptTokens: 300, seconds: 0.1 });
  expect(within(panel()).getByText("Jev 沒選定（信心不足），9 個工具都給")).toBeInTheDocument();
});

test("testReusedIntentIsShown", async () => {
  await shownIntentText({ name: "booking", confidence: null, fallbackReason: null, reused: true, promptTokens: null, seconds: 0 });
  expect(within(panel()).getByText("沿用上一輪的意圖：預約會議")).toBeInTheDocument();
});

test("testReusedAllIsShown", async () => {
  await shownIntentText({ name: null, confidence: null, fallbackReason: null, reused: true, promptTokens: null, seconds: 0 });
  expect(within(panel()).getByText("沿用上一輪：9 個工具都給")).toBeInTheDocument();
});

const modeSelect = () => within(panel()).queryByRole("combobox", { name: "模式" });

test("testModeSelectHiddenByDefault", async () => {
  await open();
  await within(panel()).findByRole("combobox", { name: "模型" });
  expect(modeSelect()).toBeNull();
});

test("testDevModeShowsAllModes", async () => {
  await open({}, undefined, devRoute);
  const select = await within(panel()).findByRole("combobox", { name: "模式" });
  expect(Array.from(select.querySelectorAll("option")).map((item) => item.value)).toEqual(["pipeline", "agent", "jev", "assistant", "assistant-jev"]);
  expect(select).toHaveValue("assistant-jev");
});

test("testDevModeIsRemembered", async () => {
  const first = await open({}, undefined, devRoute);
  await within(panel()).findByRole("combobox", { name: "模式" });
  first.unmount();
  await open();
  expect(await within(panel()).findByRole("combobox", { name: "模式" })).toBeInTheDocument();
});

test("testDevModeOff", async () => {
  localStorage.setItem("shiftpilot.dev", "1");
  await open({}, undefined, "/?dev=0");
  await within(panel()).findByRole("combobox", { name: "模型" });
  expect(modeSelect()).toBeNull();
  expect(localStorage.getItem("shiftpilot.dev")).toBeNull();
});

test("testSendsPreviousIntentAfterClarifying", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer() }) });
  const user = await askQuestion("幫我約會議");
  await within(panel()).findByText(answer.answer);
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "跟林小美");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await waitFor(() => expect(askBodies(api)).toHaveLength(2));
  expect(askBodies(api)[0]).not.toHaveProperty("previousIntent");
  expect(askBodies(api)[1].previousIntent).toBe("booking");
  expect(askBodies(api)[1]).not.toHaveProperty("openProposal");
  expect(askBodies(api)[1].history).toEqual([{ role: "user", content: "幫我約會議" }, { role: "assistant", content: answer.answer }]);
});

test("testNoPreviousIntentSentAfterTable", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer({ rows: [["晚班"]], columns: ["shift"] }) }) });
  const user = await askQuestion("第一題");
  await within(panel()).findByText(answer.answer);
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "第二題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await waitFor(() => expect(askBodies(api)).toHaveLength(2));
  expect(askBodies(api)[1]).not.toHaveProperty("previousIntent");
});

test("testDevModeOffAlwaysSendsAssistantJev", async () => {
  // 開發者模式時選了別的模式，關掉之後一律送 assistant-jev
  const first = await open({}, undefined, devRoute);
  await userEvent.setup().selectOptions(await within(panel()).findByRole("combobox", { name: "模式" }), "agent");
  first.unmount();
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: answer }) }, undefined, "/?dev=0");
  await askQuestion();
  await within(panel()).findByText(answer.answer);
  expect(askBodies(api)[0].mode).toBe("assistant-jev");
});

test("testNoPreviousIntentAfterQuery", () => {
  // query 組沒有提議工具，沿用它會讓使用者之後怎麼說都辦不了事
  const queryIntent: QaIntent = { ...bookingIntent, name: "query" };
  expect(previousTurnFor([{ id: 1, kind: "answer", result: intentAnswer({ intent: queryIntent }) }])).toBeNull();
});

test("testSendsOpenProposalFlag", async () => {
  const { api } = await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer({ proposal: openProposal }) }) });
  const user = await askQuestion("幫我約會議");
  await within(panel()).findByText(answer.answer);
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "順便請假");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await waitFor(() => expect(askBodies(api)).toHaveLength(2));
  expect(askBodies(api)[1]).toMatchObject({ openProposal: "booking" });
  expect(askBodies(api)[1]).not.toHaveProperty("previousIntent");
});

test("testMergedIntentIsShown", async () => {
  const merged: QaIntent = { name: "leave", confidence: 0.98, fallbackReason: null, reused: true, promptTokens: 300, seconds: 0.1, addedName: "manageBooking" };
  await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer({ steps: [], intent: merged }) }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("沿用上一輪：請假或撤回請假，加上 Jev 判斷：改期或取消會議（信心 0.98）")).toBeInTheDocument();
});

test("testQueryFailedShowsIntent", async () => {
  const queryIntent: QaIntent = { ...bookingIntent, name: "query", confidence: 0.9 };
  const failed = { status: 422, body: { error: { code: "QA_QUERY_FAILED", message: "助理沒有給出回答，請換個說法再試", details: { steps: [], intent: queryIntent } } } };
  await open({ "POST /api/qa/ask/stream": () => failed });
  await askQuestion();
  await within(panel()).findByText("助理沒有給出回答，請換個說法再試");
  expect(within(panel()).getByText("Jev 判斷：查詢（信心 0.90）")).toBeInTheDocument();
});

test("testDevModeSurvivesBlockedStorage", async () => {
  // 瀏覽器停用網站資料時 localStorage 會丟例外，面板仍要能用
  const blocked = () => { throw new DOMException("blocked", "SecurityError"); };
  const getSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked);
  const setSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
  try {
    await open({}, undefined, devRoute);
    expect(await within(panel()).findByRole("textbox", { name: "問題" })).toBeInTheDocument();
    // ?dev=1 仍然有效，只是記不住
    expect(within(panel()).getByRole("combobox", { name: "模式" })).toBeInTheDocument();
  } finally {
    getSpy.mockRestore();
    setSpy.mockRestore();
  }
});

test("testJevNoteShownWhenConfigured", async () => {
  await open({ "GET /api/qa/settings": () => ({ body: { jevConfigured: true } }) });
  expect(await within(panel()).findByText("問題文字會送到 Jev（TypeSafe）判斷意圖")).toBeInTheDocument();
});

test("testJevNoteHiddenWhenNotConfiguredOrOtherMode", async () => {
  const first = await open({ "GET /api/qa/settings": () => ({ body: { jevConfigured: false } }) });
  await within(panel()).findByRole("combobox", { name: "模型" });
  expect(within(panel()).queryByText(/問題文字會送到 Jev/)).toBeNull();
  first.unmount();
  await open({ "GET /api/qa/settings": () => ({ body: { jevConfigured: true } }) }, undefined, devRoute);
  const user = userEvent.setup();
  await within(panel()).findByText("問題文字會送到 Jev（TypeSafe）判斷意圖");
  await user.selectOptions(within(panel()).getByRole("combobox", { name: "模式" }), "agent");
  expect(within(panel()).queryByText(/問題文字會送到 Jev/)).toBeNull();
  await user.selectOptions(within(panel()).getByRole("combobox", { name: "模式" }), "jev");
  expect(within(panel()).getByText("問題文字會送到 Jev（TypeSafe）選工具")).toBeInTheDocument();
});

const leaveCard: QaProposal = { ...openProposal, kind: "leave.create" };

test("testOldCardStillOpenAfterClarifying", () => {
  // 請假卡還開著，後面一則是在問「哪場會議？」：沿用改期或取消，也帶上請假卡
  const reused: QaIntent = { ...bookingIntent, name: "manageBooking", reused: true };
  const entries: ChatEntry[] = [
    { id: 1, kind: "answer", result: intentAnswer({ proposal: leaveCard }) },
    { id: 2, kind: "question", text: "順便取消會議" },
    { id: 3, kind: "answer", result: intentAnswer({ intent: reused }) },
  ];
  expect(previousTurnFor(entries)).toEqual({ intent: "manageBooking", openProposal: "leave" });
});

test("testOldCardStillOpenAfterTable", () => {
  const entries: ChatEntry[] = [
    { id: 1, kind: "answer", result: intentAnswer({ proposal: leaveCard }) },
    { id: 2, kind: "question", text: "我下週有哪些會？" },
    { id: 3, kind: "answer", result: intentAnswer({ rows: [["週會"]], columns: ["title"] }) },
  ];
  expect(previousTurnFor(entries)).toEqual({ intent: null, openProposal: "leave" });
});

test("testHandledCardIsNotSentLater", () => {
  // 確認或取消後補了系統紀錄，之後的問答都不再帶那張卡
  const entries: ChatEntry[] = [
    { id: 1, kind: "answer", result: intentAnswer({ proposal: leaveCard }) },
    { id: 2, kind: "note", text: "（系統紀錄）使用者取消了這個提議" },
    { id: 3, kind: "question", text: "幫我約會議" },
    { id: 4, kind: "answer", result: intentAnswer() },
  ];
  expect(previousTurnFor(entries)).toEqual({ intent: "booking", openProposal: null });
});

test("testCardFromOtherModeIsIgnored", () => {
  // 沒有 intent 的卡片來自開發者模式的其他模式，不帶
  const entries: ChatEntry[] = [{ id: 1, kind: "answer", result: intentAnswer({ intent: undefined, proposal: leaveCard }) }];
  expect(previousTurnFor(entries)).toBeNull();
});

test("testThreeWayMergeIsShown", async () => {
  const merged: QaIntent = {
    name: "manageBooking", confidence: 0.9, fallbackReason: null, reused: true, promptTokens: 300, seconds: 0.1, addedName: "booking", cardName: "leave",
  };
  await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer({ steps: [], intent: merged }) }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("沿用上一輪：改期或取消會議，還開著的確認卡：請假或撤回請假，加上 Jev 判斷：預約會議（信心 0.90）")).toBeInTheDocument();
});

test("testCardOnlyMergeIsShown", async () => {
  const merged: QaIntent = {
    name: "manageBooking", confidence: 0.9, fallbackReason: null, reused: true, promptTokens: 300, seconds: 0.1, addedName: null, cardName: "leave",
  };
  await open({ "POST /api/qa/ask/stream": () => ({ body: intentAnswer({ steps: [], intent: merged }) }) });
  const user = await askQuestion();
  await within(panel()).findByText(answer.answer);
  await user.click(within(panel()).getByText("看工具步驟"));
  expect(within(panel()).getByText("沿用上一輪：改期或取消會議，還開著的確認卡：請假或撤回請假")).toBeInTheDocument();
});

test("testWelcomeTextIntroducesAssistant", async () => {
  await open();
  expect(await within(panel()).findByText(/^我可以幫你查組織、班表、會議和請假，也可以幫你約會議、改期或取消，或是請假、撤回假單。/)).toBeInTheDocument();
});
