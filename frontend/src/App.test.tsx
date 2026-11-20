import { screen, waitFor } from "@testing-library/react";
import { renderApp } from "./test/renderApp";

test("testAppRendersShellRegions", async () => {
  renderApp();
  expect(await screen.findByTestId("location")).toBeInTheDocument();
  await waitFor(() => expect(document.querySelector(".app")).not.toBeNull());
  expect(document.body.textContent).not.toMatch(/DEMO/);
});
