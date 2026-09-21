import type { Experiment } from "./types";

const COMPARED_METRICS: { key: keyof Experiment; label: string }[] = [
  { key: "faithfulness", label: "Faithfulness" },
  { key: "relevance", label: "Relevance" },
  { key: "hallucination_rate", label: "Hallucination rate" },
  { key: "pass_rate", label: "Pass rate" },
];

/**
 * Rows for the side-by-side chart, one per metric. Series are keyed by
 * experiment *id*: two experiments can share a name (which would collapse
 * into a single series), and a name like "metric" would clobber the axis key.
 * The name is only the legend label.
 */
export function buildComparison(
  a: Experiment,
  b: Experiment
): Record<string, string | number>[] {
  return COMPARED_METRICS.map((m) => ({
    metric: m.label,
    [a.id]: a[m.key] as number,
    [b.id]: b[m.key] as number,
  }));
}
