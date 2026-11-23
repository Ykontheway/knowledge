import { describe, expect, it } from "vitest";

import { ManagementClient } from "./client";
import { makeReplayBundle } from "./replayTestUtils";
import { ManagementError } from "./types";
import { validateManagementResponse } from "./validation";

const hash = "0123456789abcdef".repeat(4);
const { resources } = makeReplayBundle();
const job = resources.jobs[0]!;
const revision = resources.revisions[0]!;
const document = resources.documents[0]!;
const unit = resources.units[0]!;
const lineage = resources.lineages[0]!;
const diff = resources.diffs[0]!;
const evidence = resources.evidence[0]!;
const sourceRevision = {
  ...revision,
  entity_type: "source",
  navigation: {
    ...revision.navigation,
    event: "published",
    unit_id: null,
    previous_unit_id: null,
    content_hash: null,
    previous_content_hash: null,
    reverted: null,
  },
};

type ResponseName = Parameters<typeof validateManagementResponse>[0];
const requiredHashTargets: Array<[string, ResponseName, (candidate: unknown) => unknown]> = [
  ...(["config_fingerprint", "dataset_hash", "knowledge_fingerprint"] as const).flatMap((key): Array<[string, ResponseName, (candidate: unknown) => unknown]> => [
    [`JobDTO.${key}`, "GetJobResponse", (candidate) => ({ ...job, [key]: candidate })],
    [`ListJobsResponse.items[].${key}`, "ListJobsResponse", (candidate) => ({
      items: [{ ...job, [key]: candidate }], total: 1, limit: 1, offset: 0,
    })],
  ]),
  ["DocumentDTO.checksum", "GetDocumentResponse", (candidate) => ({ ...document, checksum: candidate })],
  ["UnitDTO.content_hash", "GetUnitResponse", (candidate) => ({ ...unit, content_hash: candidate })],
  ["DocumentDTO.units[].content_hash", "GetDocumentResponse", (candidate) => ({
    ...document, units: { ...document.units, items: [{ ...unit, content_hash: candidate }] },
  })],
  ["LineageDTO.versions[].content_hash", "GetLineageResponse", (candidate) => ({
    ...lineage, versions: { ...lineage.versions, items: [{ ...unit, content_hash: candidate }] },
  })],
  ...(["old", "new"] as const).map((side): [string, ResponseName, (candidate: unknown) => unknown] => [
    `DocumentDiffDTO.changes[].${side}.content_hash`, "GetDocumentDiffResponse", (candidate) => ({
      ...diff,
      changes: { ...diff.changes, items: [{ ...diff.changes.items[0]!, [side]: { ...unit, content_hash: candidate } }] },
    }),
  ]),
  ...(["content_hash", "document_checksum"] as const).map((key): [string, ResponseName, (candidate: unknown) => unknown] => [
    `EvidenceDTO.${key}`, "GetEvidenceResponse", (candidate) => ({ ...evidence, [key]: candidate }),
  ]),
];

function expectInvalid(name: ResponseName, payload: unknown): void {
  expect(() => validateManagementResponse(name, payload)).toThrowError(ManagementError);
  expect(() => validateManagementResponse(name, payload)).toThrowError(
    expect.objectContaining({ kind: "invalid_response" }),
  );
}

describe("B1 nullable hash contract regressions", () => {
  it.each([
    ["content_hash null", { ...sourceRevision.navigation, document_checksum: hash }],
    ["document_checksum null", { ...revision.navigation, document_checksum: null, content_hash: hash }],
    ["all navigation hashes null", { ...sourceRevision.navigation, document_checksum: null }],
    ["non-null hashes", { ...revision.navigation, document_checksum: hash, content_hash: hash }],
    ["optional hashes absent", {}],
  ])("accepts schema-permitted %s without rewriting the response", async (_label, navigation) => {
    const payload = { ...sourceRevision, navigation };
    const before = structuredClone(payload);
    expect(validateManagementResponse("GetRevisionResponse", payload)).toBe(payload);
    const client = new ManagementClient(async () => new Response(JSON.stringify(payload)));
    await expect(client.getRevision(payload.id)).resolves.toEqual(payload);
    expect(payload).toEqual(before);
  });

  it.each(requiredHashTargets)("keeps %s required and non-null", (_label, name, build) => {
    const valid = build(hash);
    expect(validateManagementResponse(name, valid)).toBe(valid);
    expectInvalid(name, build(null));
    expectInvalid(name, build(undefined));
  });

  it.each([
    ["uppercase", "A".repeat(64)],
    ["short", "a".repeat(63)],
    ["long", "a".repeat(65)],
    ["non-hex", "g".repeat(64)],
    ["empty", ""],
    ["whitespace", ` ${hash}`],
    ["number", 123],
    ["boolean", false],
    ["object", {}],
    ["array", [hash]],
    ["NaN", Number.NaN],
  ])("still rejects %s hashes at required and nullable paths", (_label, candidate) => {
    for (const [, name, build] of requiredHashTargets) expectInvalid(name, build(candidate));
    // 一个字段为 null 不得跳过对另一个导航 hash 的校验。
    for (const key of ["content_hash", "document_checksum"] as const) {
      expectInvalid("GetRevisionResponse", {
        ...sourceRevision,
        navigation: { ...sourceRevision.navigation, document_checksum: null, [key]: candidate },
      });
    }
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    "still rejects non-finite report numbers: %s", (actual) => {
      // 直接校验：JSON.stringify 会把非有限数值转换为 null。
      expectInvalid("GetJobResponse", {
        ...job,
        report: { ...job.report!, checks: [{ name: "recall_at_k", passed: true, actual, threshold: ">=0.8" }] },
      });
    },
  );

  it("still rejects extra fields alongside nullable navigation hashes", () => {
    expectInvalid("GetRevisionResponse", { ...sourceRevision, extra: true });
    expectInvalid("GetRevisionResponse", {
      ...sourceRevision, navigation: { ...sourceRevision.navigation, checksum: null },
    });
  });

  it.each([
    ["external href", { kind: "document", id: document.id, href: "https://evil.invalid/x" }],
    ["mismatched href", { kind: "document", id: document.id, href: `/v1/management/documents/${unit.id}` }],
    ["non-UUID id", { kind: "document", id: "not-a-uuid", href: "/v1/management/documents/not-a-uuid" }],
  ])("still rejects %s alongside a null content_hash", (_label, unsafeLink) => {
    expectInvalid("GetRevisionResponse", { ...sourceRevision, links: [unsafeLink] });
  });

  it.each(["\ud800", "\udfff", "a\ud800b"])("still rejects unpaired Unicode surrogates: %j", (text) => {
    expectInvalid("GetEvidenceResponse", { ...evidence, text });
  });
});
