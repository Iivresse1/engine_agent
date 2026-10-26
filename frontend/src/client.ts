/**
 * WebSocket 客户端（spec v2.2：前端只经协议消息与后端对话）。
 *
 * 三裁的消费侧：
 * ① 随机端口——端口来自握手文件，不硬编码；
 * ③ 断线复用 thread_id——重连带握手文件里的 thread_id（本客户端只透传，
 *    恢复语义在后端，前端不持有状态）。
 */

import WebSocket from "ws";

import { isProtocolCompatible, readHandshake } from "./handshake.js";
import { parseDownMessage, type DownMessage, type UpMessage } from "./protocol.js";

export interface ConnectOptions {
  projectDir: string;
  /** 握手文件出现的最长等待（毫秒）——后端起服务有启动间隔 */
  waitMs?: number;
  pollMs?: number;
}

export interface Connection {
  send(message: UpMessage): void;
  close(): void;
}

/** 轮询等待握手文件可用（残留文件/未就绪 → 继续等）。 */
async function waitForHandshake(
  projectDir: string,
  waitMs: number,
  pollMs: number,
): Promise<{ port: number; threadId: string } | null> {
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    const handshake = readHandshake(projectDir);
    if (handshake !== null && isProtocolCompatible(handshake)) {
      return { port: handshake.port, threadId: handshake.thread_id };
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
  return null;
}

/**
 * 连接后端。成功返回 Connection，超时/协议不兼容返回 null
 * （调用方据此退终端降级渲染——不阻塞使用）。
 */
export async function connect(
  options: ConnectOptions,
  onMessage: (message: DownMessage) => void,
  onClose: (reason: string) => void,
): Promise<Connection | null> {
  const waitMs = options.waitMs ?? 5_000;
  const pollMs = options.pollMs ?? 100;

  const target = await waitForHandshake(options.projectDir, waitMs, pollMs);
  if (target === null) return null;

  const socket = new WebSocket(`ws://127.0.0.1:${target.port}`);

  socket.on("message", (data: WebSocket.RawData) => {
    const text = typeof data === "string" ? data : data.toString("utf-8");
    const message = parseDownMessage(text);
    if (message === null) {
      onClose("后端发来不合协议的消息");
      return;
    }
    onMessage(message);
  });

  socket.on("close", () => onClose("连接已关闭"));
  socket.on("error", (error: Error) => onClose(`连接错误：${error.message}`));

  await new Promise<void>((resolve, reject) => {
    socket.once("open", () => resolve());
    socket.once("error", (error: Error) => reject(error));
  }).catch(() => undefined);

  return {
    send(message: UpMessage): void {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(message));
      }
    },
    close(): void {
      socket.close();
    },
  };
}
