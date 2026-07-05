// Tolerant parser for the partial tool-call JSON that streams from /api/generate.
// The model emits an OKFTable object incrementally; this closes the truncated
// fragment (finishes an open string, drops a dangling backslash/comma, balances
// brackets) and extracts the fields we render live. It is best-effort: when a
// fragment cannot be safely completed it returns null and the caller keeps the
// last good value, so the next delta simply fixes it.

export type PartialTable = {
  description?: string;
  columns: { name?: string; definition?: string }[];
};

export function parsePartial(raw: string): PartialTable | null {
  const completed = closeJson(raw);
  if (completed === null) return null;
  let obj: unknown;
  try {
    obj = JSON.parse(completed);
  } catch {
    return null;
  }
  if (typeof obj !== "object" || obj === null) return null;
  const o = obj as Record<string, unknown>;
  const rawCols = Array.isArray(o.columns) ? o.columns : [];
  return {
    description: typeof o.description === "string" ? o.description : undefined,
    columns: rawCols.map((c) => {
      const cc = (c ?? {}) as Record<string, unknown>;
      return {
        name: typeof cc.name === "string" ? cc.name : undefined,
        definition: typeof cc.definition === "string" ? cc.definition : undefined,
      };
    }),
  };
}

function closeJson(raw: string): string | null {
  const start = raw.indexOf("{");
  if (start === -1) return null;
  const s = raw.slice(start);

  const closers: string[] = [];
  let inStr = false;
  let escaped = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") closers.push("}");
    else if (ch === "[") closers.push("]");
    else if (ch === "}" || ch === "]") closers.pop();
  }

  let out = s;
  if (inStr) {
    if (escaped) out = out.slice(0, -1); // drop a dangling backslash
    out += '"';
  } else {
    out = out.replace(/\s+$/, "");
    if (out.endsWith(",")) out = out.slice(0, -1);
  }
  for (let i = closers.length - 1; i >= 0; i--) out += closers[i];
  return out;
}
