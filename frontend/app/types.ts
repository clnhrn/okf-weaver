export type OKFColumn = {
  name: string;
  definition: string;
  confidence: number;
  data_type: string;
  is_primary_key: boolean;
  nullable: boolean;
};

export type OKFTable = {
  name: string;
  description: string;
  confidence: number;
  is_source_of_truth: boolean;
  columns: OKFColumn[];
};

export type Bundle = { okf_version: string; tables: OKFTable[] };

export function band(c: number): "high" | "medium" | "low" {
  return c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low";
}
