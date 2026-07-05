"use client";

import { useState, type ChangeEvent } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type OKFColumn = { name: string; definition: string; confidence: number };
type OKFTable = {
  name: string;
  description: string;
  confidence: number;
  is_source_of_truth: boolean;
  columns: OKFColumn[];
};

function band(c: number): "high" | "medium" | "low" {
  return c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low";
}

export default function Home() {
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [tables, setTables] = useState<OKFTable[]>([]);
  const [expected, setExpected] = useState<string[]>([]);
  const [okfVersion, setOkfVersion] = useState("0.1");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setContent(await file.text());
    setFileName(file.name);
    e.target.value = ""; // allow re-selecting the same file
  }

  async function generate() {
    setBusy(true);
    setError(null);
    setTables([]);
    setExpected([]);
    setDone(false);
    try {
      // 1. Parse to a SchemaIR preview (422 here means bad input).
      const ing = await fetch(`${API}/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!ing.ok) throw new Error((await ing.json()).detail ?? "Could not parse schema");
      const schema = await ing.json(); // format auto-detected server-side
      setExpected(schema.tables.map((t: { name: string }) => t.name));

      // 2. Stream generation (SSE), rendering each table as it lands.
      const gen = await fetch(`${API}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(schema),
      });
      if (!gen.ok || !gen.body) throw new Error("Generation failed");
      await readSSE(gen.body, (event, data) => {
        if (event === "table") setTables((prev) => [...prev, data as OKFTable]);
        if (event === "done") {
          setOkfVersion((data as { bundle: { okf_version: string } }).bundle.okf_version);
          setDone(true);
        }
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function editTable(ti: number, patch: Partial<OKFTable>) {
    setTables((prev) => prev.map((t, i) => (i === ti ? { ...t, ...patch } : t)));
  }

  function editColumn(ti: number, ci: number, definition: string) {
    setTables((prev) =>
      prev.map((t, i) =>
        i === ti
          ? { ...t, columns: t.columns.map((c, j) => (j === ci ? { ...c, definition } : c)) }
          : t,
      ),
    );
  }

  async function download() {
    // Download the *edited* tables; the backend re-validates via OKFBundle.
    setError(null);
    const resp = await fetch(`${API}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ okf_version: okfVersion, tables }),
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({ detail: "Download failed" }));
      setError(detail.detail ?? "Download failed");
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

  const canDownload = done && tables.length > 0;

  return (
    <main>
      <h1>OKF Weaver</h1>
      <p className="sub">Turn a warehouse schema into a validated, portable OKF bundle.</p>

      <div className="row">
        <label className="file-btn">
          Upload .sql / .json
          <input type="file" accept=".sql,.json,.txt" onChange={onFile} hidden />
        </label>
        {fileName && <span className="notice">Loaded {fileName}</span>}
      </div>
      <textarea
        placeholder="Paste SQL DDL (CREATE TABLE …) or a dbt manifest.json — the format is detected automatically."
        value={content}
        onChange={(e) => {
          setContent(e.target.value);
          setFileName(null);
        }}
      />
      <p className="notice">
        Only schema names and types are sent to the model — never row data. Don&apos;t paste secrets.
      </p>
      <div className="row">
        <button onClick={generate} disabled={busy || !content.trim()}>
          {busy ? "Generating…" : "Generate OKF"}
        </button>
        <button className="secondary" onClick={download} disabled={!canDownload}>
          Approve &amp; download
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {busy && !done && expected.length > 0 && (
        <p className="status">
          <span className="spinner" /> Generating… {tables.length} of {expected.length} table
          {expected.length === 1 ? "" : "s"} done
        </p>
      )}
      {done && (
        <p className="status ok">
          ✓ Generated {tables.length} table{tables.length === 1 ? "" : "s"}. Edit anything below,
          then Approve &amp; download.
        </p>
      )}

      {tables.map((t, ti) => (
        <div className="table" key={t.name}>
          <h3>
            {t.name}{" "}
            <span className={`badge ${band(t.confidence)}`}>{t.confidence.toFixed(2)}</span>
            <label className="sot">
              <input
                type="checkbox"
                checked={t.is_source_of_truth}
                onChange={(e) => editTable(ti, { is_source_of_truth: e.target.checked })}
              />
              source of truth
            </label>
          </h3>
          <textarea
            className="edit desc"
            value={t.description}
            onChange={(e) => editTable(ti, { description: e.target.value })}
          />
          {t.columns.map((c, ci) => (
            <div className="col" key={c.name}>
              <div className="col-main">
                <strong>{c.name}</strong>
                <textarea
                  className="edit def"
                  value={c.definition}
                  onChange={(e) => editColumn(ti, ci, e.target.value)}
                />
              </div>
              <span className={`badge ${band(c.confidence)}`}>{c.confidence.toFixed(2)}</span>
            </div>
          ))}
        </div>
      ))}

      {busy &&
        expected
          .filter((name) => !tables.some((t) => t.name === name))
          .map((name) => (
            <div className="table pending" key={name}>
              <h3>
                {name} <span className="badge pending">generating…</span>
              </h3>
            </div>
          ))}
    </main>
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
