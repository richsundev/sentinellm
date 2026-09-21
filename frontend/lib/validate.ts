/** A form value the user can fix — its message is shown to them as written. */
export class FormError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FormError";
  }
}

/**
 * Parses a numeric text field. `Number("")` is 0 and `Number("abc")` is NaN,
 * which JSON turns into `null` — the server then answered with a validation
 * error that never mentioned which field was wrong.
 */
export function parseNumberField(
  label: string,
  raw: string,
  bounds: { min?: number; max?: number; integer?: boolean } = {}
): number {
  const text = raw.trim();
  const value = Number(text);
  const { min, max, integer } = bounds;
  const range =
    min !== undefined && max !== undefined
      ? ` between ${min} and ${max}`
      : min !== undefined
        ? ` of at least ${min}`
        : max !== undefined
          ? ` of at most ${max}`
          : "";
  if (text === "" || !Number.isFinite(value)) {
    throw new FormError(`${label} must be a number${range}`);
  }
  if ((min !== undefined && value < min) || (max !== undefined && value > max)) {
    throw new FormError(`${label} must be a number${range}`);
  }
  if (integer && !Number.isInteger(value)) {
    throw new FormError(`${label} must be a whole number${range}`);
  }
  return value;
}

export interface RolloutGuardFields {
  initialPct: string;
  qualityFloor: string;
  maxDrop: string;
  maxErrorRate: string;
  minSample: string;
  stepPct: string;
}

/** The guard-rail settings shared by the model and prompt canary forms. */
export function parseRolloutGuards(f: RolloutGuardFields) {
  return {
    initial_pct: parseNumberField("Initial %", f.initialPct, { min: 0, max: 100 }),
    quality_floor: parseNumberField("Quality floor", f.qualityFloor, { min: 0, max: 1 }),
    max_quality_regression: parseNumberField("Max drop vs incumbent", f.maxDrop, {
      min: 0,
      max: 1,
    }),
    max_error_rate: parseNumberField("Max error rate", f.maxErrorRate, { min: 0, max: 1 }),
    min_sample_size: parseNumberField("Min sample size", f.minSample, { min: 1, integer: true }),
    step_pct: parseNumberField("Step %", f.stepPct, { min: 1, max: 100 }),
  };
}
