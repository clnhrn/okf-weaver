"use client";

import { useMemo, useState, type ChangeEvent } from "react";
import BundleTree from "./BundleTree";
import CodeEditor from "./CodeEditor";
import FileTree from "./FileTree";
import MarkdownView from "./MarkdownView";
import { EXAMPLE_MANIFEST, EXAMPLE_SQL } from "./examples";
import type { Bundle, OKFColumn, OKFTable } from "./types";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const MODEL = "claude-sonnet-4-6";

type Phase = "idle" | "generating" | "done" | "error";
type Usage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
  estimated_cost_usd: number;
  model: string;
};

const tok = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export default function Home() {
  const [content, setContent] = useState("");
  const [context, setContext] = useState("");
  const [showContext, setShowContext] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [tables, setTables] = useState<OKFTable[]>([]);
  const [partials, setPartials] = useState<Record<string, string>>({});
  const [expected, setExpected] = useState<string[]>([]);
  const [okfVersion, setOkfVersion] = useState("0.1");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"edit" | "files">("edit");
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [selectedFile, setSelectedFile] = useState("index.md");
  const [fileMode, setFileMode] = useState<"rendered" | "raw">("rendered");
  const [usage, setUsage] = useState<Usage | null>(null);

  const detected = content.trimStart()[0];
  const format = detected === "{" || detected === "[" ? "dbt manifest.json" : "SQL DDL";
  const stats = useMemo(() => {
    const lines = content ? content.split("\n").length : 0;
    return { lines, chars: content.length };
  }, [content]);

  const pending = expected.filter((n) => !tables.some((t) => t.name === n));

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setContent(await file.text());
    setFileName(file.name);
    e.target.value = "";
  }

  function loadExample(which: "sql" | "json") {
    setContent(which === "sql" ? EXAMPLE_SQL : EXAMPLE_MANIFEST);
    setFileName(null);
  }

  async function generate() {
    setPhase("generating");
    setError(null);
    setTables([]);
    setPartials({});
    setExpected([]);
    setWarnings([]);
    setView("edit");
    setFiles(null);
    setUsage(null);
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
          const d = data as { bundle: Bundle; warnings: string[]; usage: Usage };
          setOkfVersion(d.bundle.okf_version);
          setWarnings(d.warnings ?? []);
          setUsage(d.usage ?? null);
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
      body: JSON.stringify({ okf_version: okfVersion, tables }),
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
      body: JSON.stringify({ okf_version: okfVersion, tables }),
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({ detail: "Download failed" }));
      setError(d.detail ?? "Download failed");
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "okf-bundle.zip";
    a.click();
    URL.revokeObjectURL(url);
  }

  const busy = phase === "generating";
  const canDownload = phase === "done" && tables.length > 0;

  return (
    <div className="app">
      <header className="topbar">
        <span className="mark" aria-hidden />
        <span className="wordmark">OKF Weaver</span>
        <span className="tagline mono">schema → OKF v{okfVersion} bundle</span>
        <span className="grow" />
        <span className="meta mono">model {MODEL}</span>
      </header>

      <main className="workspace">
        {/* SOURCE (raw) */}
        <section className="pane source">
          <div className="pane-head">
            <span className="label">Source</span>
            <span className={`fmt mono ${content.trim() ? "" : "faint"}`}>
              {content.trim() ? format : "—"}
            </span>
            <span className="grow" />
            <label className="ghost-btn">
              Upload
              <input type="file" accept=".sql,.json,.txt" onChange={onFile} hidden />
            </label>
          </div>
          <div className="editor-wrap">
            <CodeEditor
              value={content}
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
                {context.trim() ? " · added" : " (optional — improves accuracy)"}
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
        <div className="seam" aria-hidden>
          <span className="seam-line" />
          <span className="seam-glyph">⟩</span>
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
              <div className="seg">
                <button className={view === "edit" ? "on" : ""} onClick={() => setView("edit")}>
                  Edit
                </button>
                <button className={view === "files" ? "on" : ""} onClick={openFiles}>
                  Files
                </button>
              </div>
            )}
            <span className="grow" />
            <button className="primary" onClick={download} disabled={!canDownload}>
              Approve &amp; download .zip
            </button>
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
            ) : view === "files" && files ? (
              <div className="files-view">
                <div className="files-tree">
                  <FileTree files={files} selected={selectedFile} onSelect={setSelectedFile} />
                </div>
                <div className="files-main">
                  <div className="files-bar">
                    <span className="mono files-path">{selectedFile}</span>
                    <span className="grow" />
                    <div className="seg small">
                      <button
                        className={fileMode === "rendered" ? "on" : ""}
                        onClick={() => setFileMode("rendered")}
                      >
                        Rendered
                      </button>
                      <button
                        className={fileMode === "raw" ? "on" : ""}
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
        </section>
      </main>

      <footer className="statusbar mono">
        <span>only names + types sent to the model — never row data</span>
        <span className="grow" />
        {usage && (
          <span className="usage" title={`model ${usage.model}`}>
            {tok(usage.input_tokens)} in · {tok(usage.output_tokens)} out
            {usage.cache_read_input_tokens > 0 && ` · ${tok(usage.cache_read_input_tokens)} cached`} ·
            ~${usage.estimated_cost_usd.toFixed(4)}
          </span>
        )}
        <span className="muted">OKF v{okfVersion}</span>
      </footer>
    </div>
  );
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
