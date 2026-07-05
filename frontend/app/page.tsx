"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type OKFColumn = { name: string; definition: string; confidence: number };
type OKFTable = {
  name: string;
  description: string;
  confidence: number;
  is_source_of_truth: boolean;
  columns: OKFColumn[];
};
type Bundle = { okf_version: string; tables: OKFTable[] };

function band(c: number): "high" | "medium" | "low" {
  return c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low";
}

export default function Home() {
  const [format, setFormat] = useState<"sql" | "dbt_manifest">("sql");
  const [content, setContent] = useState("");
  const [tables, setTables] = useState<OKFTable[]>([]);
  const [expected, setExpected] = useState<string[]>([]);
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setBusy(true);
    setError(null);
    setTables([]);
    setExpected([]);
    setBundle(null);
    setDone(false);
    try {
      // 1. Parse to a SchemaIR preview (422 here means bad input).
      const ing = await fetch(`${API}/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format, content }),
      });
      if (!ing.ok) throw new Error((await ing.json()).detail ?? "Could not parse schema");
      const schema = await ing.json();
      // We know up front how many tables to expect — drives the progress UI.
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
          setBundle((data as { bundle: Bundle }).bundle);
          setDone(true);
        }
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    if (!bundle) return;
    const resp = await fetch(`${API}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bundle),
    });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "okf-bundle.zip";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main>
      <h1>OKF Weaver</h1>
      <p className="sub">Turn a warehouse schema into a validated, portable OKF bundle.</p>

      <div className="row">
        <select value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
          <option value="sql">SQL DDL</option>
          <option value="dbt_manifest">dbt manifest.json</option>
        </select>
      </div>
      <textarea
        placeholder={format === "sql" ? "CREATE TABLE orders (...);" : "Paste manifest.json"}
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <p className="notice">
        Only schema names and types are sent to the model — never row data. Don&apos;t paste secrets.
      </p>
      <div className="row">
        <button onClick={generate} disabled={busy || !content.trim()}>
          {busy ? "Generating…" : "Generate OKF"}
        </button>
        <button className="secondary" onClick={download} disabled={!bundle}>
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
          ✓ Generated {tables.length} table{tables.length === 1 ? "" : "s"}. Review below, then
          Approve &amp; download.
        </p>
      )}

      {tables.map((t) => (
        <div className="table" key={t.name}>
          <h3>
            {t.name}{" "}
            <span className={`badge ${band(t.confidence)}`}>{t.confidence.toFixed(2)}</span>
          </h3>
          <p>{t.description}</p>
          {t.columns.map((c) => (
            <div className="col" key={c.name}>
              <span>
                <strong>{c.name}</strong> — {c.definition}
              </span>
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
