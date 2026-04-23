import { assertEquals, assertThrows } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { canonicalJson } from "../canonical-json.ts";

Deno.test("primitives", () => {
  assertEquals(canonicalJson(null), "null");
  assertEquals(canonicalJson("hello"), '"hello"');
  assertEquals(canonicalJson(42), "42");
  assertEquals(canonicalJson(true), "true");
  assertEquals(canonicalJson(false), "false");
});

Deno.test("object keys are sorted lexicographically", () => {
  assertEquals(
    canonicalJson({ b: 1, a: 2, c: 3 }),
    '{"a":2,"b":1,"c":3}',
  );
});

Deno.test("nested object keys are sorted at every depth", () => {
  assertEquals(
    canonicalJson({ outer: { z: 1, a: 2 }, x: { y: 3, b: 4 } }),
    '{"outer":{"a":2,"z":1},"x":{"b":4,"y":3}}',
  );
});

Deno.test("arrays preserve order", () => {
  assertEquals(canonicalJson([3, 1, 2]), "[3,1,2]");
});

Deno.test("undefined values are dropped from objects", () => {
  assertEquals(canonicalJson({ a: 1, b: undefined, c: 2 }), '{"a":1,"c":2}');
});

Deno.test("null is preserved (not dropped)", () => {
  assertEquals(canonicalJson({ a: null }), '{"a":null}');
});

Deno.test("dates serialize as ISO string", () => {
  const d = new Date("2026-04-23T10:00:00Z");
  assertEquals(canonicalJson({ at: d }), '{"at":"2026-04-23T10:00:00.000Z"}');
});

Deno.test("non-finite numbers are rejected", () => {
  assertThrows(() => canonicalJson(NaN), Error, "non-finite");
  assertThrows(() => canonicalJson(Infinity), Error, "non-finite");
});

Deno.test("two semantically equal objects produce identical output", () => {
  const a = { x: 1, y: [1, 2], z: { a: "x" } };
  const b = { z: { a: "x" }, y: [1, 2], x: 1 };
  assertEquals(canonicalJson(a), canonicalJson(b));
});
