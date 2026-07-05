import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { THEME_INIT_SCRIPT } from "./useTheme";

export const metadata: Metadata = {
  title: "OKF Weaver",
  description: "Turn a warehouse schema into a validated, portable OKF bundle.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Set the theme before first paint so there is no light/dark flash. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
