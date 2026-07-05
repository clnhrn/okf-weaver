import { describe, expect, it } from "vitest";
import { parsePartial } from "./partialJson";

describe("parsePartial", () => {
  it("parses a complete OKFTable payload", () => {
    const full = JSON.stringify({
      name: "orders",
      description: "One row per order.",
      confidence: 0.9,
      columns: [{ name: "id", definition: "Order key.", confidence: 0.9 }],
    });
    const r = parsePartial(full)!;
    expect(r.description).toBe("One row per order.");
    expect(r.columns[0]).toEqual({ name: "id", definition: "Order key." });
  });

  it("recovers a description value truncated mid-string", () => {
    const r = parsePartial('{"name":"orders","description":"One row per ord')!;
    expect(r.description).toBe("One row per ord");
  });

  it("recovers a partial column definition", () => {
    const raw =
      '{"description":"x","columns":[{"name":"id","definition":"The order ke';
    const r = parsePartial(raw)!;
    expect(r.columns[0].name).toBe("id");
    expect(r.columns[0].definition).toBe("The order ke");
  });

  it("strips a trailing comma before closing", () => {
    const r = parsePartial('{"description":"x","confidence":0.9,')!;
    expect(r.description).toBe("x");
  });

  it("handles escaped quotes inside a streaming string", () => {
    const r = parsePartial('{"description":"a \\"quoted\\" word')!;
    expect(r.description).toBe('a "quoted" word');
  });

  it("returns null before the first opening brace", () => {
    expect(parsePartial("")).toBeNull();
    expect(parsePartial("   ")).toBeNull();
  });

  it("ignores non-string field values gracefully", () => {
    const r = parsePartial('{"description":123,"columns":[')!;
    expect(r.description).toBeUndefined();
    expect(r.columns).toEqual([]);
  });

  it("returns null for concatenated objects (repair-stall double stream)", () => {
    expect(parsePartial('{"description":"a"}{"description":"b"')).toBeNull();
  });
});
