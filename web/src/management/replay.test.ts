import { describe, expect, it } from "vitest";

import { ManagementClient } from "./client";
import { MAX_MANAGEMENT_RESPONSE_BYTES } from "./validation";
import {
  ReplayIndex,
  createReplayFetcher,
  loadReplayBundle,
  replayBundleUrl,
  validateReplayBundle,
} from "./replay";
import { ManagementError, type DocumentDTO, type EvidenceDTO } from "./types";
import { makeReplayBundle, replayIds } from "./replayTestUtils";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

describe("replay bundle validation", () => {
  it("accepts the canonical replay contract and supports local slicing", () => {
    const bundle = validateReplayBundle(makeReplayBundle());
    const index = new ReplayIndex(bundle);

    expect(index.listJobs({ status: "failed", limit: 20, offset: 0 })).toMatchObject({
      total: 1,
      items: [{ id: replayIds.candidate }],
    });
    expect(index.getDocument(replayIds.newDocument, { limit: 1, offset: 0 }).units).toMatchObject({
      total: 1,
      limit: 1,
      offset: 0,
      items: [{ id: replayIds.newUnit }],
    });
    expect(index.getLineage(replayIds.lineage, { limit: 1, offset: 1 }).versions).toMatchObject({
      total: 2,
      limit: 1,
      offset: 1,
      items: [{ id: replayIds.oldUnit }],
    });
    expect(index.getDocumentDiff(replayIds.newDocument, replayIds.oldDocument, { limit: 1, offset: 0 }).changes).toMatchObject({
      total: 1,
      limit: 1,
      offset: 0,
      items: [{ lineage_id: replayIds.lineage }],
    });
  });

  it("fails closed for broken cross references and non-100 embedded pages", () => {
    const brokenRef = makeReplayBundle();
    (brokenRef.resources.evidence as EvidenceDTO[])[1] = {
      ...brokenRef.resources.evidence[1]!,
      unit_id: "deadbeef-dead-beef-dead-beefdeadbeef",
    } as EvidenceDTO;
    expect(() => validateReplayBundle(brokenRef)).toThrowError(ManagementError);

    const brokenPage = makeReplayBundle();
    (brokenPage.resources.documents as DocumentDTO[])[1] = {
      ...brokenPage.resources.documents[1]!,
      units: { ...brokenPage.resources.documents[1]!.units, limit: 20 },
    } as DocumentDTO;
    expect(() => validateReplayBundle(brokenPage)).toThrowError(ManagementError);
  });
});

describe("replay transport", () => {
  it("serves only strict GET management routes and rejects extras", async () => {
    const fetcher = createReplayFetcher(makeReplayBundle());
    const client = new ManagementClient(fetcher);

    await expect(client.getJob(replayIds.reference)).resolves.toMatchObject({ id: replayIds.reference });
    await expect(client.getDocumentDiff(replayIds.newDocument, replayIds.oldDocument)).resolves.toMatchObject({
      new_document_id: replayIds.newDocument,
      old_document_id: replayIds.oldDocument,
    });
    await expect(client.getDocumentDiff(replayIds.newDocument, "cccccccc-cccc-cccc-cccc-cccccccccccc")).rejects.toMatchObject({ kind: "not_found" });

    await expect(
      fetcher(`/v1/management/jobs/${replayIds.reference}?secret=1`, {
        method: "GET",
        credentials: "omit",
        redirect: "error",
        headers: { accept: "application/json" },
      }),
    ).resolves.toMatchObject({ status: 400 });
    await expect(
      fetcher(`/v1/management/jobs?status=failed&status=passed`, {
        method: "GET",
        credentials: "omit",
        redirect: "error",
        headers: { accept: "application/json" },
      }),
    ).resolves.toMatchObject({ status: 400 });
    await expect(
      fetcher(`/v1/management/jobs/${replayIds.reference}/extra`, {
        method: "GET",
        credentials: "omit",
        redirect: "error",
        headers: { accept: "application/json" },
      }),
    ).resolves.toMatchObject({ status: 404 });
    await expect(
      fetcher(`/v1/management/jobs/${replayIds.reference}`, {
        method: "POST",
        credentials: "omit",
        redirect: "error",
        headers: { accept: "application/json" },
      }),
    ).resolves.toMatchObject({ status: 400 });
    await expect(
      fetcher(`/v1/management/jobs/${replayIds.reference}`, {
        method: "GET",
        credentials: "include",
        redirect: "follow",
        headers: { accept: "application/json" },
      }),
    ).resolves.toMatchObject({ status: 400 });
  });
});

describe("replay bundle loading", () => {
  it("loads replay.json under BASE_URL and preserves the validated contract", async () => {
    const bundle = makeReplayBundle();
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetcher: typeof globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return jsonResponse(bundle);
    };

    await expect(loadReplayBundle(undefined, fetcher, replayBundleUrl("/preview/app"))).resolves.toEqual(bundle);
    expect(calls).toHaveLength(1);
    expect(String(calls[0]!.input)).toBe("/preview/app/replay.json");
    expect(calls[0]!.init).toMatchObject({ method: "GET", credentials: "omit", redirect: "error" });
  });

  it("rejects malformed JSON, invalid UTF-8, and oversized bundles without reading fallback bodies", async () => {
    const malformedFetcher: typeof globalThis.fetch = async () => new Response("{not-json", { status: 200 });
    await expect(loadReplayBundle(undefined, malformedFetcher, "/replay.json")).rejects.toMatchObject({ kind: "invalid_response" });

    const invalidUtf8Fetcher: typeof globalThis.fetch = async () => new Response(new Uint8Array([0xc3, 0x28]), { status: 200 });
    await expect(loadReplayBundle(undefined, invalidUtf8Fetcher, "/replay.json")).rejects.toMatchObject({ kind: "invalid_response" });

    const oversizedFetcher: typeof globalThis.fetch = async () =>
      new Response(new Uint8Array(MAX_MANAGEMENT_RESPONSE_BYTES + 1).fill(120), { status: 200 });
    await expect(loadReplayBundle(undefined, oversizedFetcher, "/replay.json")).rejects.toMatchObject({ kind: "invalid_response" });
  });
});
