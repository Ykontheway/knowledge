import Ajv2020, { type ValidateFunction } from "ajv/dist/2020";
import schema from "./schema.json";
import { MutationError, type CommandDTO, type SessionDTO } from "./types";
import type { CommandRequest, DocumentDTO, PreviewDTO, PreviewRequest } from "./types";
import { HASH_PATTERN, UUID_PATTERN, validUnicode } from "../shared/validation";

export const MAX_TEXT_BYTES = 64 * 1024;
export const MAX_REQUEST_BYTES = 128 * 1024;
export const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
export { UUID_PATTERN, validUnicode } from "../shared/validation";
export type SchemaMap = {
  SessionDTO: SessionDTO; DocumentDTO: DocumentDTO; PreviewDTO: PreviewDTO;
  CommandDTO: CommandDTO; PreviewRequest: PreviewRequest; CommandRequest: CommandRequest;
};
const ajv = new Ajv2020({ strict: false, allErrors: false, validateFormats: true, coerceTypes: false, removeAdditional: false });
ajv.addFormat("uuid", UUID_PATTERN);
ajv.addFormat("date-time", (value: string) =>
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value)));
const validators = new Map<keyof SchemaMap, ValidateFunction>();

export function assertUuid(id: string): string {
  if (typeof id !== "string" || !UUID_PATTERN.test(id)) throw new MutationError("invalid_request");
  return id;
}
export function textMetrics(text: string) {
  return { characters: Array.from(text).length, bytes: new TextEncoder().encode(text).byteLength,
    valid: validUnicode(text) && new TextEncoder().encode(text).byteLength <= MAX_TEXT_BYTES };
}
function walk(value: unknown, error: MutationError, depth = 0): void {
  if (depth > 32) throw error;
  if (typeof value === "number" && (!Number.isFinite(value) || !Number.isSafeInteger(value))) throw error;
  if (typeof value === "string" && !validUnicode(value)) throw error;
  if (Array.isArray(value)) { for (const item of value) walk(item, error, depth + 1); return; }
  if (value === null || typeof value !== "object") return;
  if (![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw error;
  for (const [key, item] of Object.entries(value)) {
    if (["checksum", "new_checksum", "expected_checksum"].includes(key) &&
      (typeof item !== "string" || !HASH_PATTERN.test(item))) throw error;
    walk(item, error, depth + 1);
  }
}
export function validateMutation<Name extends keyof SchemaMap>(name: Name, payload: unknown): SchemaMap[Name] {
  const request = name === "PreviewRequest" || name === "CommandRequest";
  const error = new MutationError(request ? "invalid_request" : "invalid_response");
  walk(payload, error);
  let validator = validators.get(name);
  if (!validator) {
    validator = ajv.compile({ ...schema.$defs[name], $defs: schema.$defs });
    validators.set(name, validator);
  }
  if (!validator(payload)) throw error;
  const data = payload as SchemaMap[Name];
  if (name === "SessionDTO") {
    const session = data as SessionDTO;
    if (session.role !== "demo_editor" || session.capabilities.length !== 1 || session.capabilities[0] !== "document.update" ||
        !/^[A-Za-z0-9._:@-]{1,80}$/.test(session.actor_id) ||
        new Set(session.sources.map(s => s.source_id)).size !== session.sources.length) throw error;
  }
  if (name === "PreviewDTO") {
    const preview = data as PreviewDTO;
    if (preview.changed !== (preview.expected_checksum !== preview.new_checksum)) throw error;
  }
  if (name === "CommandDTO") {
    const command = data as CommandDTO;
    if (command.committed !== true || !/^[A-Za-z0-9._:@-]{1,80}$/.test(command.actor_id) ||
        command.changed !== (command.previous_document_id !== command.document_id)) throw error;
  }
  if (name === "DocumentDTO" || name === "PreviewRequest") {
    const text = (data as DocumentDTO | PreviewRequest).text;
    if (textMetrics(text).bytes > MAX_TEXT_BYTES) throw new MutationError(request ? "too_large" : "invalid_response");
  }
  return data;
}
export function serializeRequest(name: "PreviewRequest" | "CommandRequest", payload: unknown): string {
  validateMutation(name, payload);
  const json = JSON.stringify(payload);
  if (new TextEncoder().encode(json).byteLength > MAX_REQUEST_BYTES) throw new MutationError("too_large");
  return json;
}
