import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SidePanel } from "./SidePanel";
import { ToastProvider } from "./Toast";

const panel = () => screen.getByRole("complementary", { name: "問答面板" });

test("testShowsNotYetAvailableNotice", () => {
  render(<SidePanel />);
  expect(screen.getByText("Ask the desk", { selector: ".chatTitle" })).toBeInTheDocument();
  expect(screen.getByText(/問答尚未開放/)).toBeInTheDocument();
});

test("testHasModelSelectAndSendButton", () => {
  render(<SidePanel />);
  const select = screen.getByRole("combobox", { name: "模型" });
  expect(Array.from(select.querySelectorAll("option")).map((item) => item.value)).toEqual(["qwen2.5:3b", "qwen3-vl:4b-instruct"]);
  expect(screen.getByRole("textbox", { name: "問題" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "送出" })).toHaveClass("chatSend");
});

test("testSendOnlyExplainsNotAvailableAndKeepsQuestion", async () => {
  render(<ToastProvider><SidePanel /></ToastProvider>);
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: "問題" }), "明天有哪些會議？");
  await user.click(screen.getByRole("button", { name: "送出" }));
  expect(await screen.findByRole("status")).toHaveTextContent("問答尚未開放");
  expect(screen.getByRole("textbox", { name: "問題" })).toHaveValue("明天有哪些會議？");
  // 不能出現使用者的問題變成對話泡泡、或任何回答
  expect(screen.queryByText("明天有哪些會議？", { selector: ".bubble" })).toBeNull();
});

test("testModelCanBeChanged", async () => {
  render(<SidePanel />);
  await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "模型" }), "qwen3-vl:4b-instruct");
  expect(screen.getByRole("combobox", { name: "模型" })).toHaveValue("qwen3-vl:4b-instruct");
});

test("testCollapseAndExpand", async () => {
  render(<SidePanel />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "收合問答面板" }));
  expect(panel()).toHaveClass("collapsed");
  await user.click(screen.getByRole("button", { name: "展開問答面板" }));
  expect(panel()).not.toHaveClass("collapsed");
});

test("testKeyboardResizeIsClampedAndResettable", () => {
  render(<SidePanel />);
  const handle = screen.getByRole("separator", { name: "調整問答面板寬度" });
  expect(handle).toHaveAttribute("aria-valuenow", "400");
  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(handle).toHaveAttribute("aria-valuenow", "424");
  for (let index = 0; index < 20; index += 1) fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(handle).toHaveAttribute("aria-valuenow", "320");
  fireEvent.keyDown(handle, { key: "Home" });
  expect(handle).toHaveAttribute("aria-valuenow", "400");
});

test("testDragWidensPanel", () => {
  render(<SidePanel />);
  const handle = screen.getByRole("separator", { name: "調整問答面板寬度" });
  fireEvent.pointerDown(handle, { clientX: 1000 });
  fireEvent.pointerMove(window, { clientX: 950 });
  fireEvent.pointerUp(window);
  expect(handle).toHaveAttribute("aria-valuenow", "450");
});
