import { defineConfig } from "vitest/config";

// Use React's automatic JSX runtime so component tests don't need `import React`
// (matches how Next/SWC compiles the app).
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
});
