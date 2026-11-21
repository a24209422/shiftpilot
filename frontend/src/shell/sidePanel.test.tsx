import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QaAnswer, QaModel } from "../api/types";
import type { MockRoutes } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 22, 9, 30));
});
afterEach(() => vi.useRealTimers());

const models: QaModel[] = [
  { id: "qwen2.5:3b", label: "qwen2.5:3b（本機）", remote: false },
  { id: "gemini-x", label: "gemini-x（Google）", remote: true },
];
const answer: QaAnswer = {
  answer: "黃志強明天上晚班，14:00 到 23:00。", sql: "SELECT shift_name FROM day_shifts", columns: ["shift_name", "start_at"],
  rows: [["晚班", "2026-11-23T14:00:00"]], truncated: false, model: "qwen2.5:3b", remote: false,
  window: { from: "2026-08-23", to: "2027-02-20" },
};

const panel = () => screen.getByRole("complementary", { name: "問答面板" });
// 外殼要等登入狀態與權限載入完才會畫出面板，所以先等面板出現再回傳
const open = async (routes: MockRoutes = {}, permissions = ["qa.ask"]) => {
  const view = renderApp({ route: "/", permissions, routes: { "GET /api/qa/models": () => ({ body: models }), ...routes } });
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
  const { api } = await open({ "POST /api/qa/ask": () => ({ body: answer }) });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "黃志強明天上什麼班？");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("黃志強明天上晚班，14:00 到 23:00。")).toBeInTheDocument();
  expect(within(panel()).getByText("黃志強明天上什麼班？", { selector: ".bubble" })).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/qa/ask")?.body).toEqual({ question: "黃志強明天上什麼班？", model: "qwen2.5:3b" });
  await user.click(within(panel()).getByText("看查詢結果"));
  expect(within(panel()).getByRole("cell", { name: "晚班" })).toBeInTheDocument();
  expect(within(panel()).getByText("SELECT shift_name FROM day_shifts")).toBeInTheDocument();
  expect(within(panel()).getByText("資料範圍：8/23（日） ～ 2/20（六）")).toBeInTheDocument();
  expect(within(panel()).getByRole("textbox", { name: "問題" })).toHaveValue("");
});

test("testRemoteAnswerIsMarked", async () => {
  const { api } = await open({ "POST /api/qa/ask": () => ({ body: { ...answer, model: "gemini-x", remote: true } }) });
  const user = userEvent.setup();
  const select = await within(panel()).findByRole("combobox", { name: "模型" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  await user.selectOptions(select, "gemini-x");
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("gemini-x・已送到雲端")).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/qa/ask")?.body).toEqual({ question: "問題", model: "gemini-x" });
});

test("testPendingShownWhileWaitingAndDoubleSubmitSendsOnce", async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const { api } = await open({ "POST /api/qa/ask": async () => { await gate; return { body: answer }; } });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  const input = within(panel()).getByRole("textbox", { name: "問題" });
  await user.type(input, "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  expect(await within(panel()).findByText("查詢中…")).toBeInTheDocument();
  await user.type(input, "再問一次{Enter}");
  expect(api.calls.filter((call) => call.path === "/api/qa/ask")).toHaveLength(1);
  release();
  expect(await within(panel()).findByText("黃志強明天上晚班，14:00 到 23:00。")).toBeInTheDocument();
  expect(within(panel()).queryByText("查詢中…")).toBeNull();
});

test("testTruncatedNoteShowsRowCount", async () => {
  await open({ "POST /api/qa/ask": () => ({ body: { ...answer, truncated: true } }) });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.type(within(panel()).getByRole("textbox", { name: "問題" }), "問題");
  await user.click(within(panel()).getByRole("button", { name: "送出" }));
  await user.click(await within(panel()).findByText("看查詢結果"));
  expect(within(panel()).getByText("只顯示前 1 筆")).toBeInTheDocument();
});

test("testNonApiErrorShowsFallbackMessage", async () => {
  await open({ "POST /api/qa/ask": () => { throw new Error("boom"); } });
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
  await open({ "POST /api/qa/ask": () => ({ body: { ...answer, columns: ["name", "name"], rows: [["甲", { a: 1 }]] } }) });
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
  await open({ "POST /api/qa/ask": () => ({ status: 422, body: { error: { code: "QA_QUERY_FAILED", message: "查詢失敗：欄位不存在", details: { sql: "SELECT nope", error: "欄位不存在" } } } }) });
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
