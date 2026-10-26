/**
 * 握手文件发现（spec v2.2『传输层』Q71 裁①：「随机端口 + 握手文件」）。
 *
 * 后端 bind `127.0.0.1:0` 后把 `{pid, port, thread_id, protocol_version,
 * started_at}` 原子写入 `<cwd>/.project-agent/handshake.json`；前端读该文件
 * 连接——**不固定端口**。
 *
 * 残留文件（后端已死）由 pid 存活判定识别后忽略重试。
 */

import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

export interface Handshake {
  pid: number;
  port: number;
  thread_id: string;
  protocol_version: number;
  started_at: string;
}

export const HANDSHAKE_FILENAME = "handshake.json";
/** 前端支持的最高协议版本（后端更高则提示升级，不静默不兼容） */
export const PROTOCOL_VERSION = 1;

export function handshakePath(projectDir: string): string {
  return join(projectDir, ".project-agent", HANDSHAKE_FILENAME);
}

function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

/** 解析握手文件内容；形状不符返回 null。 */
export function parseHandshake(text: string): Handshake | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const record = data as Record<string, unknown>;
  if (!isInt(record["pid"]) || !isInt(record["port"])) return null;
  if (!isInt(record["protocol_version"])) return null;
  if (typeof record["thread_id"] !== "string") return null;
  if (typeof record["started_at"] !== "string") return null;
  return {
    pid: record["pid"],
    port: record["port"],
    thread_id: record["thread_id"],
    protocol_version: record["protocol_version"],
    started_at: record["started_at"],
  };
}

/** 进程存活判定（Node 无 signal 0；用 kill(pid, 0) 语义等价物）。 */
export function isPidAlive(pid: number): boolean {
  if (pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** 读握手文件；不存在/损坏/进程已死 → null（调用方据此重试）。 */
export function readHandshake(projectDir: string): Handshake | null {
  const path = handshakePath(projectDir);
  if (!existsSync(path)) return null;
  let text: string;
  try {
    text = readFileSync(path, "utf-8");
  } catch {
    return null;
  }
  const handshake = parseHandshake(text);
  if (handshake === null) return null;
  if (!isPidAlive(handshake.pid)) return null;
  return handshake;
}

export function isProtocolCompatible(handshake: Handshake): boolean {
  return handshake.protocol_version <= PROTOCOL_VERSION;
}
