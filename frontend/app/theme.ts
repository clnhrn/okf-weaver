import { createTheme } from "@uiw/codemirror-themes";
import { tags as t } from "@lezer/highlight";

// CodeMirror theme tuned to the app's slate-workbench palette. Data tokens
// (strings/types/keywords) get the structural colours; chrome stays muted.
export const editorTheme = createTheme({
  theme: "dark",
  settings: {
    background: "#0f141b",
    foreground: "#d6dbe3",
    caret: "#6b8afd",
    selection: "#22304b",
    selectionMatch: "#22304b",
    lineHighlight: "#151b2455",
    gutterBackground: "#0f141b",
    gutterForeground: "#48515f",
    gutterBorder: "transparent",
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace",
  },
  styles: [
    { tag: t.keyword, color: "#6b8afd" },
    { tag: [t.string, t.special(t.string)], color: "#45c4b0" },
    { tag: t.number, color: "#d0a54f" },
    { tag: [t.bool, t.null], color: "#d0a54f" },
    { tag: [t.comment, t.lineComment, t.blockComment], color: "#5c6675", fontStyle: "italic" },
    { tag: [t.typeName, t.className], color: "#8fb0ff" },
    { tag: [t.propertyName], color: "#a9b4c4" },
    { tag: [t.punctuation, t.separator, t.bracket, t.operator], color: "#7d8694" },
    { tag: t.variableName, color: "#d6dbe3" },
  ],
});
