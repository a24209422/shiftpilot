import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiGet, apiSend } from "../api/client";
import { createQueryClient } from "../App";
import { mockApi } from "../test/mockApi";
import { TextField } from "./fields";
import { FormError } from "./FormError";
import { useSubmit } from "./useSubmit";

function TestForm() {
  const { data } = useQuery({ queryKey: ["items"], queryFn: () => apiGet<unknown[]>("/api/items") });
  const { submit, pending, error, fieldErrors } = useSubmit(
    () => apiSend("POST", "/api/items", { name: "x" }),
    { onSuccess: () => {}, invalidate: [["items"]] },
  );
  return (
    <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
      <TextField label="名稱" value="" onChange={() => {}} error={fieldErrors.name} />
      <FormError error={error} />
      <span>{`items:${data?.length ?? "-"}`}</span>
      <button type="submit" disabled={pending}>送出</button>
    </form>
  );
}

const renderForm = () => render(<QueryClientProvider client={createQueryClient()}><TestForm /></QueryClientProvider>);

test("testDoubleSubmitSendsOnce", async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const { calls } = mockApi({
    "GET /api/items": () => ({ body: [] }),
    "POST /api/items": async () => { await gate; return { status: 201, body: {} }; },
  });
  renderForm();
  const button = await screen.findByRole("button", { name: "送出" });
  const user = userEvent.setup();
  await user.dblClick(button);
  expect(button).toBeDisabled();
  release();
  await waitFor(() => expect(button).not.toBeDisabled());
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
});

test("testFieldErrorsMapFromValidationDetails", async () => {
  mockApi({
    "GET /api/items": () => ({ body: [] }),
    "POST /api/items": () => ({ status: 422, body: { error: { code: "VALIDATION", message: "請求內容不符合格式", details: { fields: [{ loc: ["body", "name"], message: "Field required" }] } } } }),
  });
  renderForm();
  await userEvent.setup().click(await screen.findByRole("button", { name: "送出" }));
  expect(await screen.findByText("Field required")).toBeInTheDocument();
});

test("testServerMessageShown", async () => {
  mockApi({
    "GET /api/items": () => ({ body: [] }),
    "POST /api/items": () => ({ status: 422, body: { error: { code: "VALIDATION", message: "資源名稱不能是空白", details: null } } }),
  });
  renderForm();
  await userEvent.setup().click(await screen.findByRole("button", { name: "送出" }));
  expect(await screen.findByText("資源名稱不能是空白")).toBeInTheDocument();
});

test("testSuccessInvalidatesQueries", async () => {
  const { calls } = mockApi({
    "GET /api/items": () => ({ body: [] }),
    "POST /api/items": () => ({ status: 201, body: {} }),
  });
  renderForm();
  await userEvent.setup().click(await screen.findByRole("button", { name: "送出" }));
  await waitFor(() => expect(calls.filter((call) => call.method === "GET" && call.path === "/api/items")).toHaveLength(2));
});
