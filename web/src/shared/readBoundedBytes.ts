/** Mechanical byte-limit failure; callers own all domain error mapping. */
export class ResponseByteLimitError extends Error {
  readonly name = "ResponseByteLimitError";

  constructor() {
    super("Response byte limit exceeded");
  }
}

/** Read bytes only: no decoding, HTTP policy, retries, credentials or error normalization. */
export async function readBoundedBytes(response: Response, limitBytes: number): Promise<Uint8Array> {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > limitBytes) {
    throw new ResponseByteLimitError();
  }

  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > limitBytes) throw new ResponseByteLimitError();
    return bytes;
  }

  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      size += value.byteLength;
      if (size > limitBytes) {
        await reader.cancel().catch(() => undefined);
        throw new ResponseByteLimitError();
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const merged = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return merged;
}
