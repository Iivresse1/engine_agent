/**
 * 协议消息类型（严格镜像后端 `src/project_agent/messages.py` 与 spec『协议消息层』）。
 *
 * 红线：前端**不持有业务状态、不解析决议、不做路由**——只按 type 分派到渲染。
 * 消息表增删必须先改 spec + 后端，再改此处（Q68 纪律：表即契约）。
 */

/** 后端下发的断点类型（与 protocol.RoundEndReason 同字面） */
export type RoundEndReason =
  | "round"
  | "question"
  | "choice:build_way"
  | "choice:proposal"
  | "docs_done"
  | "loop_exhausted"
  | "finished";

export interface ReadyMessage {
  type: "ready";
  banner: string;
  opening_prompt: string;
}

export interface PromptMessage {
  type: "prompt";
  awaiting: string;
}

export interface RoundEndMessage {
  type: "round_end";
  reason: string;
  payload: Record<string, unknown>;
  /** 后端已折叠好的终端渲染行——前端**直接绘制，不重排文案** */
  lines: string[];
}

export interface NoticeMessage {
  type: "notice";
  text: string;
}

export interface TeachPageMessage {
  type: "teach_page";
  path: string;
  round: number;
}

export interface FarewellMessage {
  type: "farewell";
  text: string;
}

export type DownMessage =
  | ReadyMessage
  | PromptMessage
  | RoundEndMessage
  | NoticeMessage
  | TeachPageMessage
  | FarewellMessage;

export interface InputMessage {
  type: "input";
  text: string;
}

export interface QuitMessage {
  type: "quit";
}

export type UpMessage = InputMessage | QuitMessage;

const DOWN_TYPES = new Set<string>([
  "ready",
  "prompt",
  "round_end",
  "notice",
  "teach_page",
  "farewell",
]);

/** 解析一条下行 JSON（形状不符返回 null——前端不崩，交调用方提示）。 */
export function parseDownMessage(raw: string): DownMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const record = data as Record<string, unknown>;
  const type = record["type"];
  if (typeof type !== "string" || !DOWN_TYPES.has(type)) return null;

  switch (type) {
    case "ready":
      if (typeof record["banner"] !== "string") return null;
      if (typeof record["opening_prompt"] !== "string") return null;
      return {
        type: "ready",
        banner: record["banner"],
        opening_prompt: record["opening_prompt"],
      };
    case "prompt":
      if (typeof record["awaiting"] !== "string") return null;
      return { type: "prompt", awaiting: record["awaiting"] };
    case "round_end": {
      if (typeof record["reason"] !== "string") return null;
      const payload = record["payload"];
      // 与后端 messages.py 同严：必须是对象且**不是数组**
      if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
        return null;
      }
      const lines = record["lines"];
      if (!Array.isArray(lines) || lines.some((l) => typeof l !== "string")) return null;
      return {
        type: "round_end",
        reason: record["reason"],
        payload: payload as Record<string, unknown>,
        lines: lines as string[],
      };
    }
    case "notice":
      if (typeof record["text"] !== "string") return null;
      return { type: "notice", text: record["text"] };
    case "teach_page":
      if (typeof record["path"] !== "string") return null;
      if (typeof record["round"] !== "number") return null;
      return { type: "teach_page", path: record["path"], round: record["round"] };
    case "farewell":
      if (typeof record["text"] !== "string") return null;
      return { type: "farewell", text: record["text"] };
    default:
      return null;
  }
}

export function isFarewell(message: DownMessage): message is FarewellMessage {
  return message.type === "farewell";
}
