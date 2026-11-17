import { describe, expect, it, vi } from "vitest";
import { readBoundedBytes, ResponseByteLimitError } from "./readBoundedBytes";

function streamed(chunks: Uint8Array[], headers: HeadersInit = {}): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  }), { headers });
}

describe("readBoundedBytes", () => {
  it("rejects a finite oversized declaration before accessing the body", async () => {
    const response = new Response("secret", { headers: { "content-length": "5" } });
    const body = vi.spyOn(response, "body", "get");
    const buffer = vi.spyOn(response, "arrayBuffer");
    await expect(readBoundedBytes(response, 4)).rejects.toBeInstanceOf(ResponseByteLimitError);
    expect(body).not.toHaveBeenCalled();
    expect(buffer).not.toHaveBeenCalled();
    expect(response.bodyUsed).toBe(false);
  });

  it.each([undefined, "", "not-a-number", "-1", "0", "4", "Infinity", "1e309", "-Infinity"])(
    "does not turn declaration %s into a new header policy", async (length) => {
      const response = streamed([new Uint8Array([1, 2, 3, 4])],
        length === undefined ? {} : { "content-length": length });
      await expect(readBoundedBytes(response, 4)).resolves.toEqual(new Uint8Array([1, 2, 3, 4]));
      expect(response.body!.locked).toBe(false);
    },
  );

  it("merges empty and byte-sized chunks across UTF-8 without decoding them", async () => {
    const bytes = new TextEncoder().encode("中😀");
    const chunks = [new Uint8Array(), ...Array.from(bytes, byte => new Uint8Array([byte]))];
    const response = streamed(chunks);
    const result = await readBoundedBytes(response, bytes.byteLength);
    expect(result).toEqual(bytes);
    expect(new TextDecoder("utf-8", { fatal: true }).decode(result)).toBe("中😀");
    expect(response.body!.locked).toBe(false);
    await expect(readBoundedBytes(streamed([new Uint8Array([255])]), 1)).resolves.toEqual(new Uint8Array([255]));
  });

  it.each([false, true])("cancels overflow and releases the lock even if cancel rejects (%s)", async (rejectCancel) => {
    const cancel = vi.fn(() => rejectCancel ? Promise.reject(new Error("cancel failure")) : undefined);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2]));
        controller.enqueue(new Uint8Array([3, 4, 5]));
      },
      cancel,
    });
    await expect(readBoundedBytes(new Response(stream, { headers: { "content-length": "0" } }), 4))
      .rejects.toBeInstanceOf(ResponseByteLimitError);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(stream.locked).toBe(false);
  });

  it("keeps the arrayBuffer fallback and its byte bound without text/json reads", async () => {
    for (const size of [4, 5]) {
      const response = new Response(null);
      const bytes = new Uint8Array(size);
      const buffer = vi.spyOn(response, "arrayBuffer").mockResolvedValue(bytes.buffer);
      const text = vi.spyOn(response, "text");
      const json = vi.spyOn(response, "json");
      if (size === 4) await expect(readBoundedBytes(response, 4)).resolves.toEqual(bytes);
      else await expect(readBoundedBytes(response, 4)).rejects.toBeInstanceOf(ResponseByteLimitError);
      expect(buffer).toHaveBeenCalledTimes(1);
      expect(text).not.toHaveBeenCalled();
      expect(json).not.toHaveBeenCalled();
    }
    await expect(readBoundedBytes(new Response(null), 0)).resolves.toEqual(new Uint8Array());
  });

  it.each([new Error("stream failure"), new DOMException("aborted", "AbortError")])(
    "propagates a pending stream failure unchanged: %s", async (error) => {
      let controller!: ReadableStreamDefaultController<Uint8Array>;
      const cancel = vi.fn();
      const stream = new ReadableStream<Uint8Array>({ start(value) { controller = value; }, cancel });
      const reading = readBoundedBytes(new Response(stream), 4);
      const assertion = expect(reading).rejects.toBe(error);
      controller.error(error);
      await assertion;
      expect(stream.locked).toBe(false);
      expect(cancel).not.toHaveBeenCalled();
    },
  );

  it("propagates fallback failures unchanged", async () => {
    const response = new Response(null);
    const error = new DOMException("aborted", "AbortError");
    vi.spyOn(response, "arrayBuffer").mockRejectedValue(error);
    await expect(readBoundedBytes(response, 4)).rejects.toBe(error);
  });
});
