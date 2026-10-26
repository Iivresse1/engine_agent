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
export type TranscriptEntry =
  | { kind: "line"; text: string; tone: "normal" | "dim" | "notice" }
  | { kind: "block"; reason: string; lines: string[] }
  | { kind: "teach"; path: string; round: number };

const MAX_TRANSCRIPT = 200;

/** 下行消息 → 可显示条目（纯函数；界面测试直接断言此函数）。 */
export function toEntries(message: DownMessage): TranscriptEntry[] {
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
  /**
   * 下行消息订阅（依赖注入，便于测试与替换）：
   * 传入 (listener) => 取消订阅函数。默认走模块内事件桥。
   */
  subscribe?: (listener: (message: DownMessage) => void) => () => void;
}

export function App({
  connection,
  degradedReason,
  subscribe,
}: AppProps): React.ReactElement {
  const { exit } = useApp();
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  // 片 3：面板折叠（Ctrl+O 切换）/ 教学页提示（Ctrl+T 展开最近一页）
  const [panelOpen, setPanelOpen] = useState(false);
  const [teachPanelOpen, setTeachPanelOpen] = useState(false);

  // 下行消息 → 累积显示（本组件不保存业务状态，只是渲染队列）
  useEffect(() => {
    const listener = (message: DownMessage): void => {
      setEntries((prev) => {
        const next = [...prev, ...toEntries(message)];
        return next.slice(-MAX_TRANSCRIPT);
      });
      if (message.type === "teach_page") {
        setTeachPanelOpen(true);
      }
      if (message.type === "farewell") {
        setTimeout(() => exit(), 50);
      }
    };
    const unsubscribe =
      subscribe !== undefined ? subscribe(listener) : defaultSubscribe(listener);
    return unsubscribe;
  }, [subscribe, exit]);

  // 最近一条状态行（面板折叠用；前端不解析 Dashboard，只显示 /status 的 notice）
  const statusLine = [...entries]
    .reverse()
    .find((entry) => entry.kind === "line" && entry.text.startsWith("task_brief:"));

  // 最近一次断点（面板折叠用）
  const lastBreakpoint = [...entries]
    .reverse()
    .find((entry): entry is Extract<TranscriptEntry, { kind: "block" }> => entry.kind === "block");

  const lastTeach = [...entries]
    .reverse()
    .find((entry): entry is Extract<TranscriptEntry, { kind: "teach" }> => entry.kind === "teach");

  // 采集按键（Enter 提交，Esc 退出，Ctrl+O 面板，Ctrl+T 教学页）
  useInput((input, key) => {
    if (key.escape) {
      connection?.send({ type: "quit" });
      exit();
      return;
    }
    if (key.ctrl && input === "o") {
      setPanelOpen((prev) => !prev);
      return;
    }
    if (key.ctrl && input === "t") {
      setTeachPanelOpen((prev) => !prev);
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
    <TranscriptView
      entries={entries}
      draft={draft}
      submitted={submitted}
      degradedReason={degradedReason}
      panelOpen={panelOpen}
      teachPanelOpen={teachPanelOpen}
      statusLine={statusLine}
      lastBreakpoint={lastBreakpoint}
      lastTeach={lastTeach}
    />
  );
}

/** 纯展示视图（无 hooks/无副作用）——可用 renderToString 直接做渲染断言。 */
export function TranscriptView({
  entries,
  draft,
  submitted,
  degradedReason,
  panelOpen,
  teachPanelOpen,
  statusLine,
  lastBreakpoint,
  lastTeach,
}: {
  entries: TranscriptEntry[];
  draft: string;
  submitted: string | null;
  degradedReason?: string | undefined;
  panelOpen: boolean;
  teachPanelOpen: boolean;
  statusLine: TranscriptEntry | undefined;
  lastBreakpoint: Extract<TranscriptEntry, { kind: "block" }> | undefined;
  lastTeach: Extract<TranscriptEntry, { kind: "teach" }> | undefined;
}): React.ReactElement {
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
      {panelOpen ? (
        <StatusPanel statusLine={statusLine} lastBreakpoint={lastBreakpoint} />
      ) : null}
      {teachPanelOpen && lastTeach !== undefined ? (
        <TeachPanel path={lastTeach.path} round={lastTeach.round} />
      ) : null}
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
      {/* 按键提示行（常驻，观感对齐 Claude Code） */}
      <Box marginTop={1}>
        <Text color="gray">{KEY_HINTS}</Text>
      </Box>
    </Box>
  );
}

/** 常驻按键提示（片 3）。 */
const KEY_HINTS = "Enter 提交 · Ctrl+O 状态面板 · Ctrl+T 教学页 · Esc 退出";

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

/** 状态面板（片 3）：折叠显示最近状态行与最近断点——前端不解析 Dashboard。 */
function StatusPanel({
  statusLine,
  lastBreakpoint,
}: {
  statusLine: TranscriptEntry | undefined;
  lastBreakpoint: Extract<TranscriptEntry, { kind: "block" }> | undefined;
}): React.ReactElement {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginY={1}>
      <Text color="gray">{"状态面板（Ctrl+O 收起）"}</Text>
      {statusLine !== undefined && statusLine.kind === "line" ? (
        <Text>{statusLine.text}</Text>
      ) : (
        <Text color="gray">{"尚无 /status 输出"}</Text>
      )}
      {lastBreakpoint !== undefined ? (
        <Text color="gray">{`最近断点：${lastBreakpoint.reason}（${lastBreakpoint.lines.length} 行）`}</Text>
      ) : (
        <Text color="gray">{"尚无断点"}</Text>
      )}
    </Box>
  );
}

/** 教学页面板（片 3）：显示路径与轮次，提示可打开（前端不内联渲染 HTML）。 */
function TeachPanel({ path, round }: { path: string; round: number }): React.ReactElement {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1} marginY={1}>
      <Text color="green">{`教学页（第 ${round} 轮，Ctrl+T 收起）`}</Text>
      <Text>{path}</Text>
      <Text color="gray">{"用浏览器打开该文件查看图文讲解"}</Text>
    </Box>
  );
}

// 默认订阅通道（main 与 App 之间的下行消息桥；不做业务逻辑）。
// 组件测试用 subscribe prop 注入，不依赖此单例。
type Listener = (message: DownMessage) => void;
const listeners = new Set<Listener>();

export function defaultSubscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function emitDown(message: DownMessage): void {
  for (const listener of listeners) {
    listener(message);
  }
}
