"use client";

import { useState } from "react";
import { parsePartial } from "./partialJson";
import { band, type OKFColumn, type OKFTable } from "./types";

export default function BundleTree({
  tables,
  pending,
  partials,
  onTable,
  onColumn,
}: {
  tables: OKFTable[];
  pending: string[]; // names still being generated (skeleton rows)
  partials: Record<string, string>; // raw streamed JSON per pending table
  onTable: (ti: number, patch: Partial<OKFTable>) => void;
  onColumn: (ti: number, ci: number, patch: Partial<OKFColumn>) => void;
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  return (
    <div className="tree">
      {tables.map((t, ti) => {
        const open = !collapsed[t.name];
        return (
          <section className="node" key={t.name}>
            <header className="node-head">
              <button
                className="chev"
                onClick={() => setCollapsed((c) => ({ ...c, [t.name]: open }))}
                aria-label={open ? "collapse" : "expand"}
              >
                {open ? "▾" : "▸"}
              </button>
              <span className="mono tname">{t.name}</span>
              <span className={`chip conf ${band(t.confidence)}`}>{t.confidence.toFixed(2)}</span>
              <span className="colcount">
                {t.columns.length} col{t.columns.length === 1 ? "" : "s"}
              </span>
              <label className="sot" title="Mark as the canonical table for this entity">
                <input
                  type="checkbox"
                  checked={t.is_source_of_truth}
                  onChange={(e) => onTable(ti, { is_source_of_truth: e.target.checked })}
                />
                source of truth
              </label>
            </header>

            {open && (
              <div className="node-body">
                <textarea
                  className="mono desc"
                  value={t.description}
                  spellCheck={false}
                  rows={2}
                  onChange={(e) => onTable(ti, { description: e.target.value })}
                />
                <div className="cols">
                  {t.columns.map((c, ci) => (
                    <div className="crow" key={c.name}>
                      <span className="cidx mono">{String(ci + 1).padStart(2, "0")}</span>
                      <div className="cbody">
                        <div className="cmeta">
                          <span className="mono cname">{c.name}</span>
                          <input
                            className="mono ctype"
                            value={c.data_type}
                            spellCheck={false}
                            title="Inferred type (editable)"
                            onChange={(e) => onColumn(ti, ci, { data_type: e.target.value })}
                          />
                          <button
                            className={`ov ${c.is_primary_key ? "on" : ""}`}
                            title="Toggle primary key"
                            onClick={() => onColumn(ti, ci, { is_primary_key: !c.is_primary_key })}
                          >
                            PK
                          </button>
                          <button
                            className={`ov ${c.nullable ? "" : "on"}`}
                            title="Toggle nullability"
                            onClick={() => onColumn(ti, ci, { nullable: !c.nullable })}
                          >
                            {c.nullable ? "null" : "not null"}
                          </button>
                          {c.references && (
                            <span className="fk mono" title="Foreign key">
                              → {c.references}
                            </span>
                          )}
                          <span className={`chip conf ${band(c.confidence)}`}>
                            {c.confidence.toFixed(2)}
                          </span>
                        </div>
                        <textarea
                          className="mono cdef"
                          value={c.definition}
                          spellCheck={false}
                          rows={2}
                          onChange={(e) => onColumn(ti, ci, { definition: e.target.value })}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        );
      })}

      {pending.map((name) => {
        const preview = parsePartial(partials[name] ?? "");
        const cols = preview?.columns.filter((c) => c.name || c.definition) ?? [];
        const hasContent = Boolean(preview?.description) || cols.length > 0;
        return (
          <section className="node skeleton" key={name}>
            <header className="node-head">
              <span className="chev">▸</span>
              <span className="mono tname">{name}</span>
              <span className="chip pending">generating…</span>
            </header>
            {hasContent ? (
              <div className="node-body">
                {preview?.description && (
                  <p className="mono desc streaming">{preview.description}</p>
                )}
                <div className="cols">
                  {cols.map((c, ci) => (
                    <div className="crow" key={`col-${ci}`}>
                      <span className="cidx mono">{String(ci + 1).padStart(2, "0")}</span>
                      <div className="cbody">
                        <div className="cmeta">
                          <span className="mono cname">{c.name ?? "…"}</span>
                        </div>
                        <p className="mono cdef streaming">{c.definition ?? ""}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="skeleton-rows">
                <span />
                <span />
                <span />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
