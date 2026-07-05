"use client";

import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

export const THEME_KEY = "okf-theme";

// Inlined into <head> so the theme is applied before first paint (no flash).
// Mirrors the resolution logic below; keep the two in sync.
export const THEME_INIT_SCRIPT = `(function(){try{var c=localStorage.getItem('${THEME_KEY}')||'system';var d=(c==='light'||c==='dark')?c:(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');document.documentElement.dataset.theme=d;}catch(e){}})();`;

function systemTheme(): "light" | "dark" {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/**
 * Theme controller: persists the user's choice and reflects the resolved
 * light/dark value onto `<html data-theme>` (which the CSS keys off). When the
 * choice is "system" it tracks OS changes live.
 */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("dark");

  // Load the persisted choice once mounted (localStorage isn't available on the
  // server). Batched with nothing else so the apply effect below runs with the
  // real choice, matching what the pre-paint script already set — no flash.
  useEffect(() => {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") setChoice(stored);
  }, []);

  useEffect(() => {
    localStorage.setItem(THEME_KEY, choice);
    const apply = () => {
      const next = choice === "system" ? systemTheme() : choice;
      setResolved(next);
      document.documentElement.dataset.theme = next;
    };
    apply();
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [choice]);

  return { choice, setChoice, resolved };
}
