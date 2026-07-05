"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Split a leading YAML frontmatter block (--- ... ---) off the markdown body and
// parse its simple `key: value` lines for display. We only need a flat, one-line
// view of the OKF frontmatter, so a full YAML parser would be overkill.
function splitFrontmatter(src: string): { meta: [string, string][]; body: string } {
  const match = src.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!match) return { meta: [], body: src };
  const meta = match[1]
    .split("\n")
    .map((line): [string, string] | null => {
      const i = line.indexOf(":");
      if (i === -1) return null;
      return [line.slice(0, i).trim(), line.slice(i + 1).trim()];
    })
    .filter((pair): pair is [string, string] => pair !== null && pair[0] !== "");
  return { meta, body: src.slice(match[0].length) };
}

export default function MarkdownView({
  content,
  files,
  onNavigate,
}: {
  content: string;
  files: Record<string, string>;
  onNavigate: (path: string) => void;
}) {
  const { meta, body } = splitFrontmatter(content);

  return (
    <div className="md-view">
      {meta.length > 0 && (
        <dl className="md-meta mono">
          {meta.map(([key, value]) => (
            <div className="md-meta-row" key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="md-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a({ href, children, ...rest }) {
              // OKF cross-links look like `/tables/orders.md`; when they point at
              // another file in this bundle, navigate the tree instead of leaving.
              const key = href?.replace(/^\//, "") ?? "";
              if (href && files[key] !== undefined) {
                return (
                  <a
                    href={href}
                    onClick={(e) => {
                      e.preventDefault();
                      onNavigate(key);
                    }}
                    {...rest}
                  >
                    {children}
                  </a>
                );
              }
              return (
                <a href={href} target="_blank" rel="noreferrer" {...rest}>
                  {children}
                </a>
              );
            },
          }}
        >
          {body}
        </ReactMarkdown>
      </div>
    </div>
  );
}
