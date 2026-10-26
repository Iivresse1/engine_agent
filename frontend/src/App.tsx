/**
 * Ink 界面骨架（UX-3 片 2）。
 *
 * 职责边界（spec『外观与分发』+ ADR-0005）：只消费下行消息、只发上行消息；
 * 不持有 Dashboard、不解析决议、不做路由。断点文案**直接绘制后端给的 lines**，
 * 前端不重排文案（否则两处文案必然漂移）。
 */

import React, { useEffect, useState } from "react";
import { Box, Text, useApp, useInput } from "ink";

import type { Connection } from "./client.js";
import type { DownMessage } from "./protocol.js";
import { displayWidth } from "./width.js";

/** 会话里累积的一条可显示内容。 */
type TranscriptEntry =
  | { kind: "line"; text: string; tone: "normal" | "dim" | "notice" }
  | { kind: "block"; reason: string; lines: string[] }
  | { kind: "teach"; path: string; round: number };

const MAX_TRANSCRIPT = 200;

function toEntries(message: DownMessage): TranscriptEntry[] {
  switch (message.type) {
    case "ready":
      return [
        { kind: "line", text: message.banner, tone: "normal" },
        { kind: "line", text: "", tone: "dim" },
        { kind: "line", text: message.opening_prompt, tone: "normal" },
      ];
    case "prompt":
      return [];
    case "round_end":
      return [{ kind: "block", reason: message.reason, lines: message.lines }];
    case "notice":
      return [{ kind: "line", text: message.text, tone: "notice" }];
    case "teach_page":
      return [{ kind: "teach", path: message.path, round: message.round }];
    case "farewell":
      return [{ kind: "line", text: message.text, tone: "dim" }];
    default:
      return [];
  }
}

export interface AppProps {
  connection: Connection | null;
  /** 连接失败时的降级提示（前端未接线 → 后端裸终端） */
  degradedReason?: string;
}

export function App({ connection, degradedReason }: AppProps): React.ReactElement {
  const { exit } = useApp();
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);

  // 下行消息 → 累积显示（本组件不保存业务状态，只是渲染队列）
  useEffect(() => {
    if (connection === null) return;
    // 连接对象由 main 注入 onMessage 回调，这里通过全局事件桥接
    const listener = (message: DownMessage): void => {
      setEntries((prev) => {
        const next = [...prev, ...toEntries(message)];
        return next.slice(-MAX_TRANSCRIPT);
      });
      if (message.type === "farewell") {
        setTimeout(() => exit(), 50);
      }
    };
    registerListener(listener);
    return () => unregisterListener(listener);
  }, [connection, exit]);

  // 采集按键（Enter 提交，Esc 退出）
  useInput((input, key) => {
    if (key.escape) {
      connection?.send({ type: "quit" });
      exit();
      return;
    }
    if (key.return) {
      const text = draft.trim();
      setDraft("");
      if (text === "") return;
      setSubmitted(text);
      setEntries((prev) => [
        ...prev.slice(-MAX_TRANSCRIPT),
        { kind: "line", text: `❯ ${text}`, tone: "dim" },
      ]);
      connection?.send({ type: "input", text });
      return;
    }
    if (key.backspace || key.delete) {
      setDraft((prev) => prev.slice(0, -1));
      return;
    }
    if (input && !key.ctrl && !key.meta) {
      setDraft((prev) => prev + input);
    }
  });

  return (
    <Box flexDirection="column">
      {degradedReason !== undefined ? (
        <Box marginBottom={1}>
          <Text color="yellow">{`前端未接线：${degradedReason}（请用后端终端模式）`}</Text>
        </Box>
      ) : null}
      {entries.map((entry, index) => (
        <EntryView key={index} entry={entry} />
      ))}
      <Box>
        <Text color="cyan">{"❯ "}</Text>
        <Text>{draft}</Text>
        <Text color="gray">{"▏"}</Text>
      </Box>
      {submitted !== null ? (
        <Box>
          <Text color="gray">{`· 已提交 ${displayWidth(submitted)} 列`}</Text>
        </Box>
      ) : null}
    </Box>
  );
}

function EntryView({ entry }: { entry: TranscriptEntry }): React.ReactElement {
  if (entry.kind === "line") {
    const color =
      entry.tone === "dim" ? "gray" : entry.tone === "notice" ? "yellow" : undefined;
    return color === undefined ? (
      <Text>{entry.text}</Text>
    ) : (
      <Text color={color}>{entry.text}</Text>
    );
  }
  if (entry.kind === "teach") {
    return <Text color="green">{`教学页已生成：${entry.path}（第 ${entry.round} 轮）`}</Text>;
  }
  return (
    <Box flexDirection="column">
      <Text color="magenta">{`断点 · ${entry.reason}`}</Text>
      {entry.lines.map((line, index) => (
        <Text key={index}>{line}</Text>
      ))}
    </Box>
  );
}

// 极简事件桥（main 与 App 之间的下行消息通道；不做业务逻辑）
type Listener = (message: DownMessage) => void;
const listeners = new Set<Listener>();

export function registerListener(listener: Listener): void {
  listeners.add(listener);
}

export function unregisterListener(listener: Listener): void {
  listeners.delete(listener);
}

export function emitDown(message: DownMessage): void {
  for (const listener of listeners) {
    listener(message);
  }
}
