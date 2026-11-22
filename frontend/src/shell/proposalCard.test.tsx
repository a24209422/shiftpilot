import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QaAnswer, QaModel, QaProposal } from "../api/types";
import type { MockCall, MockResponse, MockRoutes } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 22, 9, 30));
});
afterEach(() => vi.useRealTimers());

const models: QaModel[] = [{ id: "qwen2.5:3b", label: "qwen2.5:3b（本機）", remote: false }];
const bookingBody = { title: "週會", category: "會議", startAt: "2026-11-24T10:00", endAt: "2026-11-24T11:00", resourceIds: [3], participantIds: [5] };
const bookingProposal: QaProposal = {
  kind: "booking.create",
  request: { method: "POST", path: "/api/booking/bookings", body: bookingBody },
  summary: [{ label: "標題", value: "週會" }, { label: "時間", value: "11/24（二） 10:00–11:00" }],
  quote: null,
};
const leaveBody = { leaveTypeId: 1, startAt: "2026-11-24T09:00", endAt: "2026-11-24T18:00", reason: "看醫生" };
const leaveProposal: QaProposal = {
  kind: "leave.create",
  request: { method: "POST", path: "/api/leave/requests", body: leaveBody },
  summary: [{ label: "假別", value: "特休" }],
  quote: { path: "/api/leave/requests/quote", body: leaveBody },
};
const cancelProposal: QaProposal = {
  kind: "booking.cancel",
  request: { method: "POST", path: "/api/booking/bookings/7/cancel", body: null },
  summary: [{ label: "會議", value: "週會" }],
  quote: null,
};
const answerWith = (proposal: QaProposal | null, text = "幫你準備好了，請確認。"): QaAnswer => ({
  answer: text, sql: "", columns: [], rows: [], truncated: false, model: "qwen2.5:3b", remote: false, mode: "assistant",
  window: { from: "2026-08-23", to: "2027-02-20" }, proposal,
});

const panel = () => screen.getByRole("complementary", { name: "問答面板" });
const writes = (calls: MockCall[]) => calls.filter((call) => call.method !== "GET" && call.path !== "/api/qa/ask" && !call.path.endsWith("/quote"));

// 切到助理模式問一題，回答帶著提議時面板會畫出確認卡
async function askWith(routes: MockRoutes) {
  const view = renderApp({ route: "/", permissions: ["qa.ask"], routes: { "GET /api/qa/models": () => ({ body: models }), ...routes } });
  await screen.findByRole("complementary", { name: "問答面板" });
  const user = userEvent.setup();
  await within(panel()).findByRole("combobox", { name: "模型" });
  await user.selectOptions(within(panel()).getByRole("combobox", { name: "模式" }), "assistant");
  const ask = async (text: string) => {
    await user.type(within(panel()).getByRole("textbox", { name: "問題" }), text);
    await user.click(within(panel()).getByRole("button", { name: "送出" }));
  };
  await ask("幫我排會議");
  return { ...view, user, ask };
}

test("testBookingConfirmCallsApiAndNotes", async () => {
  const { api, user } = await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(bookingProposal) }),
    "POST /api/booking/bookings": () => ({ body: { id: 42, ...bookingBody } }),
  });
  expect(await within(panel()).findByText("11/24（二） 10:00–11:00")).toBeInTheDocument();
  await user.click(within(panel()).getByRole("button", { name: "確認" }));
  expect(await within(panel()).findByText("（系統紀錄）使用者已確認，建立了會議 #42")).toBeInTheDocument();
  expect(within(panel()).getByText("已完成")).toBeInTheDocument();
  expect(within(panel()).queryByRole("button", { name: "確認" })).toBeNull();
  const call = api.calls.find((item) => item.method === "POST" && item.path === "/api/booking/bookings");
  expect(call?.body).toEqual(bookingBody);
});

test("testParticipantConflictThenOverride", async () => {
  let count = 0;
  const { api, user } = await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(bookingProposal) }),
    "POST /api/booking/bookings": () => {
      count += 1;
      if (count === 1) {
        return { status: 409, body: { error: { code: "PARTICIPANT_CONFLICT", message: "參加者不方便", details: { conflicts: [{ employeeId: 5, name: "黃志強", reason: "請假", title: null, startAt: null, endAt: null }] } } } };
      }
      return { body: { id: 43, ...bookingBody } };
    },
  });
  await user.click(await within(panel()).findByRole("button", { name: "確認" }));
  expect(await within(panel()).findByText("有參加者在這個時段不方便：")).toBeInTheDocument();
  await user.click(within(panel()).getByRole("button", { name: "仍要排" }));
  expect(await within(panel()).findByText("（系統紀錄）使用者已確認，建立了會議 #43")).toBeInTheDocument();
  const bodies = api.calls.filter((item) => item.path === "/api/booking/bookings").map((item) => item.body);
  expect(bodies).toEqual([bookingBody, { ...bookingBody, acknowledgeWarnings: true }]);
});

test("testResourceConflictIsFailure", async () => {
  const { user } = await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(bookingProposal) }),
    "POST /api/booking/bookings": () => ({
      status: 409,
      body: { error: { code: "RESOURCE_CONFLICT", message: "資源在這個時段已被預約", details: { conflicts: [{ bookingId: 9, title: "團隊週會", startAt: "2026-11-24T10:00", endAt: "2026-11-24T11:00", resourceId: 3, resourceName: "A 會議室" }] } } },
    }),
  });
  await user.click(await within(panel()).findByRole("button", { name: "確認" }));
  expect(await within(panel()).findByText("（系統紀錄）送出失敗：資源在這個時段已被預約")).toBeInTheDocument();
  expect(within(panel()).getByText(/A 會議室：團隊週會/)).toBeInTheDocument();
  expect(within(panel()).queryByRole("button", { name: "仍要排" })).toBeNull();
});

test("testOverrideFlagDoesNotLeakIntoRetry", async () => {
  let count = 0;
  const { api, user } = await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(bookingProposal) }),
    "POST /api/booking/bookings": () => {
      count += 1;
      if (count === 1) {
        return { status: 409, body: { error: { code: "PARTICIPANT_CONFLICT", message: "參加者不方便", details: { conflicts: [{ employeeId: 5, name: "黃志強", reason: "請假", title: null, startAt: null, endAt: null }] } } } };
      }
      if (count === 2) return { status: 422, body: { error: { code: "VALIDATION_ERROR", message: "標題太長", details: null } } };
      return { body: { id: 44, ...bookingBody } };
    },
  });
  await user.click(await within(panel()).findByRole("button", { name: "確認" }));
  const override = await within(panel()).findByRole("button", { name: "仍要排" });
  // 同一個 act 裡連點兩下：第二下時畫面還沒變成送出中，按鈕還沒停用
  act(() => { override.click(); override.click(); });
  expect(await within(panel()).findByText("（系統紀錄）送出失敗：標題太長")).toBeInTheDocument();
  await user.click(within(panel()).getByRole("button", { name: "確認" }));
  expect(await within(panel()).findByText("（系統紀錄）使用者已確認，建立了會議 #44")).toBeInTheDocument();
  const bodies = api.calls.filter((item) => item.path === "/api/booking/bookings").map((item) => item.body);
  expect(bodies).toEqual([bookingBody, { ...bookingBody, acknowledgeWarnings: true }, bookingBody]);
});

test("testLeaveConfirmWaitsForQuote", async () => {
  let finishQuote: (response: MockResponse) => void = () => {};
  await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(leaveProposal) }),
    "POST /api/leave/requests/quote": () => new Promise<MockResponse>((resolve) => { finishQuote = resolve; }),
  });
  expect(await within(panel()).findByRole("button", { name: "確認" })).toBeDisabled();
  act(() => finishQuote({ body: { hours: 8, remainingAfter: 48, conflicts: [] } }));
  expect(await within(panel()).findByText("時數 8 小時")).toBeInTheDocument();
  expect(within(panel()).getByRole("button", { name: "確認" })).toBeEnabled();
});

test("testLeaveCardShowsQuote", async () => {
  const { api } = await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(leaveProposal) }),
    "POST /api/leave/requests/quote": () => ({ body: { hours: 8, remainingAfter: 48, conflicts: [] } }),
  });
  expect(await within(panel()).findByText("時數 8 小時")).toBeInTheDocument();
  expect(within(panel()).getByText("扣完剩 48 小時")).toBeInTheDocument();
  expect(api.calls.find((item) => item.path === "/api/leave/requests/quote")?.body).toEqual(leaveBody);
  expect(within(panel()).getByRole("button", { name: "確認" })).toBeEnabled();
});

test("testLeaveQuoteConflictAndFailure", async () => {
  await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(leaveProposal) }),
    "POST /api/leave/requests/quote": () => ({ status: 422, body: { error: { code: "VALIDATION_ERROR", message: "結束時間要晚於開始時間", details: null } } }),
  });
  expect(await within(panel()).findByText("結束時間要晚於開始時間")).toBeInTheDocument();
  expect(within(panel()).getByRole("button", { name: "確認" })).toBeDisabled();
});

test("testCancelDoesNotCallApi", async () => {
  const { api, user } = await askWith({ "POST /api/qa/ask": () => ({ body: answerWith(cancelProposal) }) });
  await user.click(await within(panel()).findByRole("button", { name: "取消" }));
  expect(await within(panel()).findByText("（系統紀錄）使用者取消了這個提議")).toBeInTheDocument();
  expect(within(panel()).queryByRole("button", { name: "確認" })).toBeNull();
  expect(writes(api.calls)).toHaveLength(0);
});

test("testOlderProposalIsSuperseded", async () => {
  let count = 0;
  const { ask } = await askWith({
    "POST /api/qa/ask": () => { count += 1; return { body: answerWith(bookingProposal, `第 ${count} 次提議`) }; },
  });
  await within(panel()).findByText("第 1 次提議");
  await ask("改成下午");
  await within(panel()).findByText("第 2 次提議");
  expect(within(panel()).getByText("已被新的提議取代")).toBeInTheDocument();
  expect(within(panel()).getAllByRole("button", { name: "確認" })).toHaveLength(1);
});

test("testConfirmErrorIsShown", async () => {
  const { user } = await askWith({
    "POST /api/qa/ask": () => ({ body: answerWith(cancelProposal) }),
    "POST /api/booking/bookings/7/cancel": () => ({ status: 404, body: { error: { code: "NOT_FOUND", message: "找不到這筆排程", details: null } } }),
  });
  await user.click(await within(panel()).findByRole("button", { name: "確認" }));
  expect(await within(panel()).findByText("找不到這筆排程")).toBeInTheDocument();
  expect(within(panel()).getByText("（系統紀錄）送出失敗：找不到這筆排程")).toBeInTheDocument();
});
