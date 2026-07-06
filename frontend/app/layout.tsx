import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Space_Grotesk, JetBrains_Mono } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";
import { THEME_INIT_SCRIPT } from "./useTheme";

// Fonts from the OKF Weaver logo lockup: Space Grotesk for the wordmark,
// JetBrains Mono for the tagline. next/font self-hosts them, so no external
// request is made at runtime and the CSP stays strict.
const display = Space_Grotesk({
  subsets: ["latin"],
  weight: ["600"],
  variable: "--font-display",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OKF Weaver",
  description: "Turn any relational database schema into a validated, portable OKF bundle.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        {/* Set the theme before first paint so there is no light/dark flash. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        {children}
        {/* Cookieless, account-free page + funnel analytics. On Vercel the
            script and beacon are same-origin (/_vercel/insights/*), so the
            strict CSP needs no change. */}
        <Analytics />
      </body>
    </html>
  );
}
