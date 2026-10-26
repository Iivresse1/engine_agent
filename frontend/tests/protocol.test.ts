/**
 * 协议层与握手层的纯函数测试（前端只测这两层——界面由 Ink 渲染，不做快照）。
 *
 * 表即契约：消息表与后端 `messages.py` 同源，形状断言在此镜像。
 */

import { describe, expect, it } from "vitest";

import {
  isPidAlive,
  isProtocolCompatible,
  parseHandshake,
  PROTOCOL_VERSION,
  type Handshake,
} from "../src/handshake.js";
import { isFarewell, parseDownMessage } from "../src/protocol.js";
import { displayWidth, padEndWidth } from "../src/width.js";

describe("parseDownMessage（六类下行）", () => {
  it("ready：横幅与开场提示", () => {
    const message = parseDownMessage(
      JSON.stringify({
        type: "ready",
        banner: "Project Agent。输入 /help 查看命令。",
        opening_prompt: "今天要做什么呢？",
      }),
    );
    expect(message).toEqual({
      type: "ready",
      banner: "Project Agent。输入 /help 查看命令。",
      opening_prompt: "今天要做什么呢？",
    });
  });

  it("round_end：payload 与 lines 原样透传（前端不重排文案）", () => {
    const message = parseDownMessage(
      JSON.stringify({
        type: "round_end",
        reason: "choice:build_way",
        payload: { explanation: "解释" },
        lines: ["    1. 对话 —— 像聊天一样推进"],
      }),
    );
    expect(message?.type).toBe("round_end");
    if (message?.type === "round_end") {
      expect(message.reason).toBe("choice:build_way");
      expect(message.lines).toEqual(["    1. 对话 —— 像聊天一样推进"]);
    }
  });

  it("prompt / notice / teach_page / farewell 各自解析", () => {
    expect(parseDownMessage(JSON.stringify({ type: "prompt", awaiting: "actor" }))).toEqual({
      type: "prompt",
      awaiting: "actor",
    });
    expect(parseDownMessage(JSON.stringify({ type: "notice", text: "回执" }))).toEqual({
      type: "notice",
      text: "回执",
    });
    expect(
      parseDownMessage(JSON.stringify({ type: "teach_page", path: "teach-me/R1/index.html", round: 1 })),
    ).toEqual({ type: "teach_page", path: "teach-me/R1/index.html", round: 1 });
    expect(parseDownMessage(JSON.stringify({ type: "farewell", text: "再见" }))).toEqual({
      type: "farewell",
      text: "再见",
    });
  });

  it("未知 type / 坏 JSON / 缺字段 / lines 含非串 一律 null", () => {
    expect(parseDownMessage(JSON.stringify({ type: "nope" }))).toBeNull();
    expect(parseDownMessage("{oops")).toBeNull();
    expect(parseDownMessage(JSON.stringify({ type: "notice" }))).toBeNull();
    expect(
      parseDownMessage(JSON.stringify({ type: "round_end", reason: "r", payload: {}, lines: [1] })),
    ).toBeNull();
    expect(parseDownMessage(JSON.stringify({ type: "round_end", reason: "r", payload: [] , lines: [] }))).toBeNull();
  });

  it("isFarewell 仅对 farewell 为真", () => {
    expect(isFarewell({ type: "farewell", text: "再见" })).toBe(true);
    expect(isFarewell({ type: "notice", text: "hi" })).toBe(false);
  });
});

describe("握手文件（随机端口发现）", () => {
  const valid = {
    pid: 1234,
    port: 51234,
    thread_id: "t-1",
    protocol_version: 1,
    started_at: "2026-10-26T12:00:00",
  };

  it("六字段往返保真", () => {
    expect(parseHandshake(JSON.stringify(valid))).toEqual(valid as Handshake);
  });

  it("缺字段 / 坏 JSON / 非整数端口 一律 null", () => {
    expect(parseHandshake(JSON.stringify({ pid: 1, port: 2 }))).toBeNull();
    expect(parseHandshake("garbage")).toBeNull();
    expect(parseHandshake(JSON.stringify({ ...valid, port: "51234" }))).toBeNull();
    expect(parseHandshake(JSON.stringify({ ...valid, port: 51234.5 }))).toBeNull();
  });

  it("协议版本兼容判定：不高于前端支持版本即兼容", () => {
    expect(isProtocolCompatible({ ...valid, protocol_version: PROTOCOL_VERSION } as Handshake)).toBe(true);
    expect(isProtocolCompatible({ ...valid, protocol_version: PROTOCOL_VERSION + 1 } as Handshake)).toBe(false);
  });

  it("存活判定：本进程真、非法 pid 假", () => {
    expect(isPidAlive(process.pid)).toBe(true);
    expect(isPidAlive(0)).toBe(false);
    expect(isPidAlive(-1)).toBe(false);
    expect(isPidAlive(999_999_999)).toBe(false);
  });
});

describe("中文字宽（不得用 String.length）", () => {
  it("全角算 2 列", () => {
    expect(displayWidth("断点")).toBe(4);
    expect(displayWidth("abc")).toBe(3);
    expect(displayWidth("断点 abc")).toBe(8);
  });

  it("length 与显示宽度确实不同（哨兵）", () => {
    const text = "断点";
    expect(text.length).toBe(2);
    expect(displayWidth(text)).toBe(4);
    expect(displayWidth(text)).not.toBe(text.length);
  });

  it("padEndWidth 按列数补齐", () => {
    expect(padEndWidth("断点", 6)).toBe("断点  ");
    expect(padEndWidth("abcdef", 3)).toBe("abcdef");
  });
});
