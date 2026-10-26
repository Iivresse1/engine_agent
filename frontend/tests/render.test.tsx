/**
 * 渲染测试（片 3）：用 ink 的 renderToString 对**纯展示视图**做真实渲染断言。
 *
 * App 有 hooks/副作用，不做快照；TranscriptView 是纯函数组件，
 * 直接把一组 entries 渲染成字符串，断言面板、按键提示、断点块是否出现。
 */

import React from "react";
import { renderToString } from "ink";
import { describe, expect, it } from "vitest";

import { TranscriptView, toEntries } from "../src/App.js";

function renderView(entries: ReturnType<typeof toEntries>, overrides: Partial<Parameters<typeof TranscriptView>[0]> = {}): string {
  const blocks = entries.filter((entry) => entry.kind === "block");
  const teaches = entries.filter((entry) => entry.kind === "teach");
  return renderToString(
    React.createElement(TranscriptView, {
      entries,
      draft: "草稿",
      submitted: null,
      panelOpen: false,
      teachPanelOpen: false,
      statusLine: undefined,
      lastBreakpoint: blocks.at(-1),
      lastTeach: teaches.at(-1),
      ...overrides,
    }),
    { columns: 100 },
  );
}

const readyEntries = toEntries({
  type: "ready",
  banner: "Project Agent。输入 /help 查看命令。",
  opening_prompt: "今天要做什么呢？",
});

describe("TranscriptView 渲染（片 3）", () => {
  it("开场三行 + 输入框 + 按键提示常驻", () => {
    const frame = renderView(readyEntries, { draft: "" });
    expect(frame).toContain("Project Agent。输入 /help 查看命令。");
    expect(frame).toContain("今天要做什么呢？");
    expect(frame).toContain("❯");
    expect(frame).toContain("Ctrl+O 状态面板");
    expect(frame).toContain("Esc 退出");
  });

  it("断点块渲染：标题 + 后端给的 lines 原样（前端不重排）", () => {
    const entries = toEntries({
      type: "round_end",
      reason: "choice:build_way",
      payload: {},
      lines: ["    1. 对话 —— 像聊天一样推进", "    推荐：简化文档 —— 轻量直接"],
    });
    const frame = renderView(entries);
    expect(frame).toContain("断点 · choice:build_way");
    expect(frame).toContain("1. 对话 —— 像聊天一样推进");
    expect(frame).toContain("推荐：简化文档 —— 轻量直接");
  });

  it("状态面板（Ctrl+O）展开：显示最近断点信息；收起时不显示", () => {
    const entries = toEntries({
      type: "round_end",
      reason: "round",
      payload: {},
      lines: ["a", "b"],
    });
    const open = renderView(entries, { panelOpen: true });
    expect(open).toContain("状态面板（Ctrl+O 收起）");
    expect(open).toContain("最近断点：round（2 行）");
    const closed = renderView(entries, { panelOpen: false });
    expect(closed).not.toContain("状态面板（Ctrl+O 收起）");
  });

  it("教学页面板（Ctrl+T）：显示路径与轮次", () => {
    const entries = toEntries({ type: "teach_page", path: "teach-me/R3/index.html", round: 3 });
    const frame = renderView(entries, { teachPanelOpen: true });
    expect(frame).toContain("教学页（第 3 轮，Ctrl+T 收起）");
    expect(frame).toContain("teach-me/R3/index.html");
  });

  it("降级提示：前端未接线时明确指向后端终端模式", () => {
    const frame = renderView(readyEntries, { degradedReason: "握手文件未出现" });
    expect(frame).toContain("前端未接线：握手文件未出现");
    expect(frame).toContain("后端终端模式");
  });

  it("中文字宽生效：提交列数按东亚宽度而非 length", () => {
    const frame = renderView(readyEntries, { submitted: "断点" });
    // "断点" 显示 4 列（不是 length=2）
    expect(frame).toContain("已提交 4 列");
  });
});
