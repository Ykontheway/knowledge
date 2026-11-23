import { describe, expect, it } from "vitest";
import { HASH_PATTERN, UUID_PATTERN, validUnicode } from "./validation";
import { assertUuid as assertManagementUuid } from "../management/validation";
import { ManagementError } from "../management/types";
import { assertUuid as assertMutationUuid, UUID_PATTERN as mutationUuid, validUnicode as mutationUnicode } from "../mutations/validation";
import { MutationError } from "../mutations/types";

describe("shared validation primitives", () => {
  it("preserves the exact regex source/flags and mutation exports", () => {
    expect(UUID_PATTERN.source).toBe("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
    expect(UUID_PATTERN.flags).toBe("i");
    expect(HASH_PATTERN.source).toBe("^[0-9a-f]{64}$");
    expect(HASH_PATTERN.flags).toBe("");
    expect(mutationUuid).toBe(UUID_PATTERN);
    expect(mutationUnicode).toBe(validUnicode);
  });

  it.each(["00000000-0000-0000-0000-000000000000", "ABCDEF01-ABCD-ABCD-ABCD-ABCDEF012345"])(
    "accepts UUID %s without introducing version restrictions or normalization", (uuid) => {
      expect(UUID_PATTERN.test(uuid)).toBe(true);
      expect(assertManagementUuid(uuid)).toBe(uuid);
      expect(assertMutationUuid(uuid)).toBe(uuid);
    },
  );

  it.each(["", "not-a-uuid", " abcdef01-abcd-abcd-abcd-abcdef012345", "abcdef01-abcd-abcd-abcd-abcdef012345x"])(
    "retains separate domain errors for UUID %s", (uuid) => {
      expect(UUID_PATTERN.test(uuid)).toBe(false);
      expect(() => assertManagementUuid(uuid)).toThrow(ManagementError);
      expect(() => assertManagementUuid(uuid)).toThrow("请求参数无效。");
      expect(() => assertMutationUuid(uuid)).toThrow(MutationError);
      expect(() => assertMutationUuid(uuid)).toThrow("invalid_request");
    },
  );

  it("retains the distinct runtime type guards in UUID wrappers", () => {
    const value = { toString: () => "00000000-0000-0000-0000-000000000000" } as unknown as string;
    expect(assertManagementUuid(value)).toBe(value);
    expect(() => assertMutationUuid(value)).toThrow(MutationError);
  });

  it.each([["a".repeat(64), true], ["0123456789abcdef".repeat(4), true], ["A".repeat(64), false],
    ["g".repeat(64), false], ["a".repeat(63), false], ["a".repeat(65), false], ["", false]])(
    "retains lowercase-only hash matching: %s", (hash, expected) => {
      expect(HASH_PATTERN.test(hash as string)).toBe(expected);
    },
  );

  it.each([["", true], ["中文\u0000", true], ["中😀", true], ["\ud800\udc00", true], ["\udbff\udfff", true],
    ["\ud800", false], ["\udbff", false], ["\udc00", false], ["\udfff", false], ["a\ud800b", false],
    ["\ud800\ud800\udc00", false], ["\udc00\ud800", false], ["😀\udfff", false], ["😀😀", true]])(
    "retains surrogate pairing rules: %j", (text, expected) => {
      expect(validUnicode(text as string)).toBe(expected);
    },
  );
});
