import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ThemeToggle from "./ThemeToggle";
import type { ThemeChoice } from "./useTheme";

const LABEL: Record<ThemeChoice, string> = { light: "Light", dark: "Dark", system: "Auto" };

function render(choice: ThemeChoice) {
  return renderToStaticMarkup(<ThemeToggle choice={choice} onChange={() => {}} />);
}

// Pulls the aria-pressed value for a given option's <button>, regardless of
// attribute order in the emitted HTML.
function pressedFor(html: string, label: string) {
  const button = html
    .split("<button")
    .find((chunk) => chunk.includes(`title="${label} theme"`));
  return button?.match(/aria-pressed="(true|false)"/)?.[1];
}

describe("ThemeToggle", () => {
  it("always renders all three options, not just the active one", () => {
    const html = render("system");
    expect(html).toContain("Light theme");
    expect(html).toContain("Auto theme");
    expect(html).toContain("Dark theme");
  });

  it.each(["light", "dark", "system"] as ThemeChoice[])("marks only the %s button as pressed", (choice) => {
    const html = render(choice);
    for (const opt of ["light", "dark", "system"] as ThemeChoice[]) {
      expect(pressedFor(html, LABEL[opt])).toBe(opt === choice ? "true" : "false");
    }
  });

  it("renders a distinct icon per choice rather than reusing one glyph", () => {
    const icons = (["light", "dark", "system"] as ThemeChoice[]).map((c) => render(c));
    expect(new Set(icons).size).toBe(3);
  });
});
