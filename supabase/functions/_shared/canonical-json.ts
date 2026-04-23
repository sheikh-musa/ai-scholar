/**
 * Deterministic JSON serialization for content_hash stability.
 *
 * Used by ruling_audit_log producer: a ruling's canonical content_hash MUST
 * be reproducible by any third-party verifier given the same logical
 * content. This requires:
 *   - object keys sorted lexicographically at every depth
 *   - no insignificant whitespace
 *   - undefined values dropped (but null preserved)
 *   - arrays preserve order (semantically meaningful)
 *
 * Numbers, strings, booleans, null pass through. Dates serialize as ISO
 * strings. Anything else throws — we never silently swallow uncanonical
 * input on the audit path.
 */

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`canonicalJson: non-finite number ${value} not allowed`);
    }
    return String(value);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value instanceof Date) return JSON.stringify(value.toISOString());
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>)
      .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
      .sort();
    return (
      "{" +
      keys
        .map((k) => JSON.stringify(k) + ":" + canonicalJson((value as Record<string, unknown>)[k]))
        .join(",") +
      "}"
    );
  }
  throw new Error(`canonicalJson: unsupported type ${typeof value}`);
}
