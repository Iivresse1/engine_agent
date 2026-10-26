/**
 * 片 3 面板/按键的纯逻辑测试。
 *
 * 直接测 `App.tsx` 导出的真实 `toEntries`（不写镜像副本——镜像会与实现漂移）。
 * Ink 的渲染细节不测；界面观感由人工冒烟把关。
 */

import { describe, expect, it } from "vitest";

import { toEntries, type TranscriptEntry } from "../src/App.js";

function lastBlock(entries: TranscriptEntry[]): Extract<TranscriptEntry, { kind: "block" }> | undefined {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry !== undefined && entry.kind === "block") return entry;
  }
  return undefined;
}

function lastTeach(entries: TranscriptEntry[]): Extract<TranscriptEntry, { kind: "teach" }> | undefined {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry !== undefined && entry.kind === "teach") return entry;
  }
  return undefined;
}

describe("toEntries（六类下行的显示折叠）", () => {
  it("ready → 横幅 + 空行 + 开场提示（三行）", () => {
    expect(
      toEntries({
        type: "ready",
        banner: "Project Agent。输入 /help 查看命令。",
        opening_prompt: "今天要做什么呢？",
      }),
    ).toEqual([
      { kind: "line", text: "Project Agent。输入 /help 查看命令。", tone: "normal" },
      { kind: "line", text: "", tone: "dim" },
      { kind: "line", text: "今天要做什么呢？", tone: "normal" },
    ]);
  });

  it("round_end → 块条目，lines 原样保留（前端不重排文案）", () => {
    const lines = ["    1. 对话 —— 像聊天一样推进", "    推荐：简化文档"];
    expect(toEntries({ type: "round_end", reason: "choice:build_way", payload: {}, lines })).toEqual([
      { kind: "block", reason: "choice:build_way", lines },
    ]);
  });

  it("notice → notice 色调行；teach_page → 教学条目；farewell → dim 行", () => {
    expect(toEntries({ type: "notice", text: "task_brief: 记账 CLI" })).toEqual([
      { kind: "line", text: "task_brief: 记账 CLI", tone: "notice" },
    ]);
    expect(toEntries({ type: "teach_page", path: "teach-me/R1/index.html", round: 1 })).toEqual([
      { kind: "teach", path: "teach-me/R1/index.html", round: 1 },
    ]);
    expect(toEntries({ type: "farewell", text: "再见" })).toEqual([
      { kind: "line", text: "再见", tone: "dim" },
    ]);
  });

  it("prompt 不产生显示条目（等待输入无需刷屏）", () => {
    expect(toEntries({ type: "prompt", awaiting: "actor" })).toEqual([]);
  });
});

describe("面板取数（片 3）", () => {
  it("最近断点 = 最后一条 round_end", () => {
    const entries = [
      ...toEntries({ type: "round_end", reason: "round", payload: {}, lines: ["a"] }),
      ...toEntries({ type: "round_end", reason: "choice:build_way", payload: {}, lines: ["b", "c"] }),
      ...toEntries({ type: "notice", text: "收尾" }),
    ];
    const last = lastBlock(entries);
    expect(last?.reason).toBe("choice:build_way");
    expect(last?.lines.length).toBe(2);
  });

  it("无断点时返回 undefined（渲染面板兜底文案）", () => {
    expect(lastBlock(toEntries({ type: "notice", text: "hi" }))).toBeUndefined();
  });

  it("最近教学页 = 最后一条 teach_page", () => {
    const entries = [
      ...toEntries({ type: "teach_page", path: "teach-me/R1/index.html", round: 1 }),
      ...toEntries({ type: "teach_page", path: "teach-me/R2/index.html", round: 2 }),
    ];
    expect(lastTeach(entries)?.path).toBe("teach-me/R2/index.html");
  });

  it("状态行取自 /status 的 notice（前端不解析 Dashboard）", () => {
    const entries = [
      ...toEntries({ type: "notice", text: "task_brief: 记账 CLI" }),
      ...toEntries({ type: "notice", text: "其它提示" }),
    ];
    const status = entries.filter(
      (entry): entry is Extract<TranscriptEntry, { kind: "line" }> =>
        entry.kind === "line" && entry.text.startsWith("task_brief:"),
    );
    expect(status.at(-1)?.text).toBe("task_brief: 记账 CLI");
  });
});
