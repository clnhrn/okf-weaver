"use client";

import { useMemo, useRef, useState, type ChangeEvent, type CSSProperties } from "react";
import BundleTree from "./BundleTree";
import CodeEditor from "./CodeEditor";
import ConfirmModal from "./ConfirmModal";
import FileTree from "./FileTree";
import ThemeToggle from "./ThemeToggle";
import MarkdownView from "./MarkdownView";
import ErdView from "./ErdView";
import { EXAMPLE_MANIFEST, EXAMPLE_SQL } from "./examples";
import type { Bundle, OKFColumn, OKFTable } from "./types";
import { useTheme } from "./useTheme";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type Phase = "idle" | "generating" | "done" | "error";

// Actions that need a user's explicit go-ahead before proceeding — either
// because they'd discard unsaved work (reset/upload/example), or because
// skipping them measurably lowers output quality (generating without
// context) — are routed through this so we can confirm first.
type ConfirmAction =
  | { kind: "reset" }
  | { kind: "upload"; file: File }
  | { kind: "example"; which: "sql" | "json" }
  | { kind: "generate-without-context" };

export default function Home() {
  const [content, setContent] = useState("");
  const [context, setContext] = useState("");
  const [showContext, setShowContext] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [tables, setTables] = useState<OKFTable[]>([]);
  const [partials, setPartials] = useState<Record<string, string>>({});
  const [expected, setExpected] = useState<string[]>([]);
  const [okfVersion, setOkfVersion] = useState("0.1");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"edit" | "files" | "erd">("edit");
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [selectedFile, setSelectedFile] = useState("index.md");
  const [fileMode, setFileMode] = useState<"rendered" | "raw">("rendered");
  const [split, setSplit] = useState(50); // left pane width, % of the workspace
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const { choice: themeChoice, setChoice: setThemeChoice, resolved: themeMode } = useTheme();

  const detected = content.trimStart()[0];
  const format = detected === "{" || detected === "[" ? "dbt manifest.json" : "SQL DDL";
  const stats = useMemo(() => {
    const lines = content ? content.split("\n").length : 0;
    return { lines, chars: content.length };
  }, [content]);

  const pending = expected.filter((n) => !tables.some((t) => t.name === n));

  const SPLIT_MIN = 22;
  const SPLIT_MAX = 78;
  function startResize(e: React.PointerEvent) {
    e.preventDefault();
    const ws = workspaceRef.current;
    if (!ws) return;
    const move = (ev: PointerEvent) => {
      const rect = ws.getBoundingClientRect();
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      setSplit(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, pct)));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }
  function resizeKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowLeft") setSplit((s) => Math.max(SPLIT_MIN, s - 2));
    else if (e.key === "ArrowRight") setSplit((s) => Math.min(SPLIT_MAX, s + 2));
    else return;
    e.preventDefault();
  }

  // True once there's pasted content or an already-generated bundle that a
  // content-replacing action (New / Upload / Load example) would discard.
  function hasUnsavedWork() {
    return content.trim().length > 0 || tables.length > 0;
  }

  // Shared by every action that replaces the source: the previously
  // generated bundle no longer matches the new content, so drop it rather
  // than leave a stale bundle sitting behind an enabled Download button.
  function clearGeneratedBundle() {
    setTables([]);
    setPartials({});
    setExpected([]);
    setWarnings([]);
    setPhase("idle");
    setError(null);
    setView("edit");
    setFiles(null);
    setSelectedFile("index.md");
    setFileMode("rendered");
  }

  async function applyUpload(file: File) {
    setContent(await file.text());
    setFileName(file.name);
    // Suggest a bundle name from the filename (editable); user can override.
    if (!name.trim()) setName(file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
    clearGeneratedBundle();
  }

  function applyExample(which: "sql" | "json") {
    setContent(which === "sql" ? EXAMPLE_SQL : EXAMPLE_MANIFEST);
    setFileName(null);
    clearGeneratedBundle();
  }

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (hasUnsavedWork()) setConfirmAction({ kind: "upload", file });
    else await applyUpload(file);
  }

  function loadExample(which: "sql" | "json") {
    if (hasUnsavedWork()) setConfirmAction({ kind: "example", which });
    else applyExample(which);
  }

  function requestReset() {
    if (hasUnsavedWork()) setConfirmAction({ kind: "reset" });
    else reset();
  }

  function reset() {
    setConfirmAction(null);
    setContent("");
    setContext("");
    setShowContext(false);
    setFileName(null);
    setName("");
    clearGeneratedBundle();
  }

  async function confirmPendingAction() {
    const action = confirmAction;
    if (!action) return;
    setConfirmAction(null);
    if (action.kind === "reset") reset();
    else if (action.kind === "upload") await applyUpload(action.file);
    else if (action.kind === "example") applyExample(action.which);
    else await runGenerate();
  }

  function cancelPendingAction() {
    // Declining the context nudge should lead somewhere useful, not just
    // close the dialog — surface the panel the user was just told to fill in.
    if (confirmAction?.kind === "generate-without-context") setShowContext(true);
    setConfirmAction(null);
  }

  function generate() {
    if (context.trim() === "") {
      setConfirmAction({ kind: "generate-without-context" });
      return;
    }
    void runGenerate();
  }

  async function runGenerate() {
    setPhase("generating");
    setError(null);
    setTables([]);
    setPartials({});
    setExpected([]);
    setWarnings([]);
    setView("edit");
    setFiles(null);
    try {
      const ing = await fetch(`${API}/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!ing.ok) throw new Error((await ing.json()).detail ?? "Could not parse schema");
      const schema = await ing.json();
      const order: string[] = schema.tables.map((t: { name: string }) => t.name);
      setExpected(order);

      const gen = await fetch(`${API}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schema, context: context.trim() || null }),
      });
      if (!gen.ok || !gen.body) throw new Error("Generation failed — check the backend is running.");
      await readSSE(gen.body, (event, data) => {
        if (event === "token") {
          const { table, delta } = data as { table: string; delta: string };
          setPartials((prev) => ({ ...prev, [table]: (prev[table] ?? "") + delta }));
        }
        if (event === "error") {
          const d = data as { message?: string };
          throw new Error(d.message ?? "Generation failed.");
        }
        if (event === "table") {
          const t = data as OKFTable;
          setPartials((prev) => {
            const next = { ...prev };
            delete next[t.name];
            return next;
          });
          setTables((prev) =>
            [...prev, t].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name)),
          );
        }
        if (event === "done") {
          const d = data as { bundle: Bundle; warnings: string[] };
          setOkfVersion(d.bundle.okf_version);
          setWarnings(d.warnings ?? []);
        }
      });
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  function editTable(ti: number, patch: Partial<OKFTable>) {
    setTables((prev) => prev.map((t, i) => (i === ti ? { ...t, ...patch } : t)));
  }
  function editColumn(ti: number, ci: number, patch: Partial<OKFColumn>) {
    setTables((prev) =>
      prev.map((t, i) =>
        i === ti
          ? { ...t, columns: t.columns.map((c, j) => (j === ci ? { ...c, ...patch } : c)) }
          : t,
      ),
    );
  }

  async function openFiles() {
    // Re-serialize the current (edited) bundle to preview the exact files.
    setError(null);
    const resp = await fetch(`${API}/api/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ okf_version: okfVersion, name, tables }),
    });
    if (!resp.ok) {
      setError("Preview failed");
      return;
    }
    const data = (await resp.json()) as { files: Record<string, string> };
    setFiles(data.files);
    setSelectedFile(data.files["index.md"] ? "index.md" : Object.keys(data.files)[0]);
    setView("files");
  }

  async function download() {
    setError(null);
    const resp = await fetch(`${API}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ okf_version: okfVersion, name, tables }),
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({ detail: "Download failed" }));
      setError(d.detail ?? "Download failed");
      return;
    }
    // Let the server's slugified name drive the filename (single source of truth).
    const disposition = resp.headers.get("content-disposition") ?? "";
    const fname = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)?.[1] ?? "okf-bundle.zip";
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = decodeURIComponent(fname);
    a.click();
    URL.revokeObjectURL(url);
  }

  const busy = phase === "generating";
  const canDownload = phase === "done" && tables.length > 0;

  return (
    <div className="app">
      <header className="topbar">
        <svg className="mark" viewBox="0 0 76 76" aria-hidden focusable="false">
          <g stroke="var(--accent-2)" strokeWidth="6" strokeLinecap="round">
            <line x1="20" y1="28" x2="56" y2="28" />
            <line x1="20" y1="48" x2="56" y2="48" />
          </g>
          <g stroke="var(--accent)" strokeWidth="6" strokeLinecap="round">
            <line x1="30" y1="16" x2="30" y2="60" />
            <line x1="46" y1="16" x2="46" y2="60" />
          </g>
        </svg>
        <span className="wordmark">
          OKF <span className="wordmark-accent">Weaver</span>
        </span>
        <span className="tagline mono">context + DDL → OKF v{okfVersion} bundle</span>
        <span className="grow" />
        <ThemeToggle choice={themeChoice} onChange={setThemeChoice} />
      </header>

      <main
        className="workspace"
        ref={workspaceRef}
        style={{ "--fr-left": `${split}fr`, "--fr-right": `${100 - split}fr` } as CSSProperties}
      >
        {/* SOURCE (raw) */}
        <section className="pane source">
          <div className="pane-head">
            <span className="label">Source</span>
            <span className={`fmt mono ${content.trim() ? "" : "faint"}`}>
              {content.trim() ? format : "—"}
            </span>
            <span className="grow" />
            <button
              className="ghost-btn"
              onClick={requestReset}
              disabled={!hasUnsavedWork() && phase === "idle"}
              title="Clear the schema and bundle to start over"
            >
              New
            </button>
            <label className="ghost-btn">
              Upload
              <input type="file" accept=".sql,.json,.txt" onChange={onFile} className="vh" />
            </label>
          </div>
          <div className="editor-wrap">
            <CodeEditor
              value={content}
              mode={themeMode}
              onChange={(v) => {
                setContent(v);
                setFileName(null);
              }}
              placeholder="Paste SQL DDL or a dbt manifest.json — format is detected automatically."
            />
          </div>
          <div className="ctx">
            <button className="ctx-toggle" onClick={() => setShowContext((s) => !s)}>
              {showContext ? "▾" : "▸"} Context
              <span className="muted">
                {context.trim() ? " · added" : " (optional — sharpens definitions on ambiguous columns)"}
              </span>
            </button>
            {showContext && (
              <textarea
                className="mono ctx-input"
                value={context}
                spellCheck={false}
                onChange={(e) => setContext(e.target.value)}
                placeholder="Domain notes & glossary, e.g. 'B2C marketplace. revenue = net of tax and refunds. status ∈ {pending, shipped, cancelled}. tier ∈ {bronze, silver, gold}.' — steers definitions and lifts confidence on ambiguous columns."
              />
            )}
          </div>
          <div className="pane-foot">
            <span className="mono muted">
              {stats.lines} lines · {stats.chars} chars
              {fileName ? ` · ${fileName}` : ""}
            </span>
            <span className="grow" />
            <button className="primary" onClick={generate} disabled={busy || !content.trim()}>
              {busy ? `Generating ${tables.length}/${expected.length || "…"}` : "Generate ▸"}
            </button>
          </div>
        </section>

        {/* TRANSFORM SEAM (signature element) */}
        <div
          className="seam"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize panes"
          aria-valuenow={Math.round(split)}
          aria-valuemin={SPLIT_MIN}
          aria-valuemax={SPLIT_MAX}
          tabIndex={0}
          onPointerDown={startResize}
          onKeyDown={resizeKey}
          onDoubleClick={() => setSplit(50)}
          title="Drag to resize · double-click to reset"
        >
          <span className="seam-line" />
          <span className="seam-grip" aria-hidden />
          <span className="seam-line" />
        </div>

        {/* BUNDLE (structured) */}
        <section className="pane bundle">
          <div className="pane-head">
            <span className="label">Bundle</span>
            {phase === "generating" && (
              <span className="status mono">
                <span className="spinner" /> {tables.length}/{expected.length}
              </span>
            )}
            {phase === "done" && (
              <span className="status ok mono">
                ✓ {tables.length} table{tables.length === 1 ? "" : "s"}
                {warnings.length ? ` · ${warnings.length} warning${warnings.length === 1 ? "" : "s"}` : " · valid"}
              </span>
            )}
            {phase === "done" && (
              <div className="seg" role="group" aria-label="Bundle view">
                <button
                  className={view === "edit" ? "on" : ""}
                  aria-pressed={view === "edit"}
                  onClick={() => setView("edit")}
                >
                  Edit
                </button>
                <button
                  className={view === "files" ? "on" : ""}
                  aria-pressed={view === "files"}
                  onClick={openFiles}
                >
                  Files
                </button>
                <button
                  className={view === "erd" ? "on" : ""}
                  aria-pressed={view === "erd"}
                  onClick={() => setView("erd")}
                >
                  ERD
                </button>
              </div>
            )}
            <span className="grow" />
          </div>

          <div className="bundle-body">
            {phase === "error" ? (
              <div className="state error">
                <span className="state-icon">!</span>
                <p className="state-title">Couldn&apos;t build the bundle</p>
                <p className="mono state-msg">{error}</p>
                <button className="ghost-btn" onClick={generate} disabled={!content.trim()}>
                  Retry
                </button>
              </div>
            ) : phase === "idle" ? (
              <div className="state empty">
                <span className="state-icon">{"{ }"}</span>
                <p className="state-title">No bundle yet</p>
                <p className="muted">Paste or upload a schema on the left, then Generate. Or load an example:</p>
                <div className="ex-row">
                  <button className="ghost-btn" onClick={() => loadExample("sql")}>
                    schema.sql
                  </button>
                  <button className="ghost-btn" onClick={() => loadExample("json")}>
                    manifest.json
                  </button>
                </div>
              </div>
            ) : view === "erd" ? (
              <ErdView tables={tables} />
            ) : view === "files" && files ? (
              <div className="files-view">
                <div className="files-tree">
                  <FileTree files={files} selected={selectedFile} onSelect={setSelectedFile} />
                </div>
                <div className="files-main">
                  <div className="files-bar">
                    <span className="mono files-path">{selectedFile}</span>
                    <span className="grow" />
                    <div className="seg small" role="group" aria-label="File display mode">
                      <button
                        className={fileMode === "rendered" ? "on" : ""}
                        aria-pressed={fileMode === "rendered"}
                        onClick={() => setFileMode("rendered")}
                      >
                        Rendered
                      </button>
                      <button
                        className={fileMode === "raw" ? "on" : ""}
                        aria-pressed={fileMode === "raw"}
                        onClick={() => setFileMode("raw")}
                      >
                        Raw
                      </button>
                    </div>
                  </div>
                  {fileMode === "rendered" && selectedFile.endsWith(".md") ? (
                    <MarkdownView
                      content={files[selectedFile]}
                      files={files}
                      onNavigate={setSelectedFile}
                    />
                  ) : (
                    <pre className="files-content mono">{files[selectedFile]}</pre>
                  )}
                </div>
              </div>
            ) : (
              <>
                {warnings.length > 0 && (
                  <div className="warnbar">
                    {warnings.map((w) => (
                      <div className="mono" key={w}>
                        ⚠ {w}
                      </div>
                    ))}
                  </div>
                )}
                <BundleTree
                  tables={tables}
                  pending={busy ? pending : []}
                  partials={partials}
                  onTable={editTable}
                  onColumn={editColumn}
                />
              </>
            )}
          </div>

          {phase === "done" && (
            <div className="pane-foot">
              <span className="grow" />
              <input
                className="bundle-name"
                value={name}
                spellCheck={false}
                aria-label="Bundle name"
                placeholder="Name this bundle"
                title="Names the .zip and the bundle's index.md"
                onChange={(e) => setName(e.target.value)}
              />
              <button className="primary" onClick={download} disabled={!canDownload}>
                Download OKF Bundle (.zip)
              </button>
            </div>
          )}
        </section>
      </main>

      <footer className="statusbar mono">
        <span>only names + types sent to the model — never row data</span>
        <span className="grow" />
        <span className="muted">OKF v{okfVersion}</span>
      </footer>

      {confirmAction && (
        <ConfirmModal
          {...confirmCopy(confirmAction)}
          onConfirm={confirmPendingAction}
          onCancel={cancelPendingAction}
        />
      )}
    </div>
  );
}

function confirmCopy(
  action: ConfirmAction,
): { title: string; message: string; confirmLabel: string; tone?: "danger" | "neutral" } {
  switch (action.kind) {
    case "reset":
      return {
        title: "Clear schema and bundle?",
        message: "This clears the pasted schema, context, and generated bundle. This can't be undone.",
        confirmLabel: "Clear",
      };
    case "upload":
      return {
        title: "Replace with uploaded file?",
        message: `This replaces the current schema with "${action.file.name}" and discards the generated bundle. This can't be undone.`,
        confirmLabel: "Replace",
      };
    case "example":
      return {
        title: "Load the example schema?",
        message: "This replaces the current schema with the example and discards the generated bundle. This can't be undone.",
        confirmLabel: "Load example",
      };
    case "generate-without-context":
      return {
        title: "Generate without context?",
        message:
          "No context added — this schema will be documented from structure alone, and definitions on ambiguous columns will score lower confidence. Add context first, or continue anyway.",
        confirmLabel: "Generate anyway",
        tone: "neutral",
      };
  }
}

async function readSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: unknown) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      const event = lines.find((l) => l.startsWith("event: "))?.slice(7);
      const data = lines.find((l) => l.startsWith("data: "))?.slice(6);
      if (event && data) onEvent(event, JSON.parse(data));
    }
  }
}
