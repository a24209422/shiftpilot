import { render } from "@testing-library/react";
import { App } from "./App";

test("testAppRendersShellRegions", () => {
  render(<App />);
  expect(document.querySelector(".app")).not.toBeNull();
  expect(document.body.textContent).not.toMatch(/DEMO|Ask the desk/);
});
