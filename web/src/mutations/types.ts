import type { CommandDTO as GeneratedCommand, SessionDTO as GeneratedSession } from "./types.gen";

export type { PreviewDTO, PreviewRequest, CommandRequest, DocumentDTO, SourceSessionDTO } from "./types.gen";
// The fixed wire contract always includes these default-valued Pydantic fields.
export type SessionDTO = GeneratedSession & { role: "demo_editor" };
export type CommandDTO = GeneratedCommand & { committed: true };

export type MutationErrorKind =
  | "unauthorized" | "not_found" | "conflict" | "expired" | "too_large"
  | "unsupported_media" | "invalid_request" | "invalid_response"
  | "unavailable" | "timeout" | "aborted" | "network";

// Never attach transport causes, payloads, tokens, URLs or server error messages.
export class MutationError extends Error {
  readonly kind: MutationErrorKind;
  readonly status?: number;
  constructor(kind: MutationErrorKind, status?: number) {
    super(kind);
    this.name = "MutationError";
    this.kind = kind;
    this.status = status;
  }
}
export function safeError(error: unknown): MutationError {
  return error instanceof MutationError ? error : new MutationError("network");
}
export const ERROR_MESSAGES: Record<MutationErrorKind, string> = {
  unauthorized: "没有隔离副本的更新权限。请由服务端管理员配置授权，浏览器不接收密钥。",
  not_found: "尚未查到已提交记录，请用原请求重试或等待。",
  conflict: "版本或请求发生冲突，需重新加载当前文档并预览。草稿会保留，不会自动覆盖。",
  expired: "预览已过期，请重新预览。只有新预览才会使用新幂等键。",
  too_large: "文本或请求超过大小限制。",
  unsupported_media: "服务端不接受此内容类型。",
  invalid_request: "请求不符合受控变更要求。",
  invalid_response: "未能验证服务端响应，请勿据此判断提交结果。",
  unavailable: "受控变更服务未启用或暂不可用。版本快照和原有只读页面仍可使用。",
  timeout: "等待超时。",
  aborted: "已停止等待。",
  network: "连接中断，暂时无法确认服务端结果。",
};
