"use client";

import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { json } from "@codemirror/lang-json";
import { EditorView } from "@codemirror/view";
import { editorTheme } from "./theme";

function isJsonish(s: string): boolean {
  const head = s.trimStart()[0];
  return head === "{" || head === "[";
}

export default function CodeEditor({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  // Language follows the same JSON-vs-SQL heuristic the backend uses to route.
  const lang = isJsonish(value) ? json() : sql();
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={editorTheme}
      extensions={[lang, EditorView.lineWrapping]}
      placeholder={placeholder}
      height="100%"
      style={{ height: "100%", fontSize: "12.5px" }}
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        highlightActiveLine: true,
        highlightActiveLineGutter: true,
        autocompletion: false,
        bracketMatching: true,
      }}
    />
  );
}
