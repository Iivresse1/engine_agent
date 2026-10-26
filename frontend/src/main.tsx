/**
 * 前端入口（UX-3 片 2/4）：连后端 → 渲染 Ink 界面；连不上或环境不支持 → 退降级。
 *
 * 关键：**Ink 需要 TTY（raw mode）**——管道/重定向/无终端环境下渲染会抛
 * "Raw mode is not supported"。此时不应崩溃：打印降级说明并以非零码退出，
 * 由 `engine` 判断后回落到裸终端 REPL（spec『兼容降级』）。
 *
 * 用法：`engine-ui [项目目录]`（默认当前目录）。
 */

import React from "react";
import { render } from "ink";

import { App, emitDown } from "./App.js";
import { connect, type Connection } from "./client.js";

function readProjectDir(argv: string[]): string {
  const arg = argv.find((item) => item !== "--" && !item.startsWith("-"));
  return arg ?? process.cwd();
}

/** 当前环境能否承载 Ink（stdin 须是 TTY 且支持 raw mode）。 */
export function canRenderInk(stream: NodeJS.ReadStream = process.stdin): boolean {
  const isTTY = (stream as NodeJS.ReadStream & { isTTY?: boolean }).isTTY === true;
  const setRawMode = (stream as NodeJS.ReadStream & { setRawMode?: unknown }).setRawMode;
  return isTTY && typeof setRawMode === "function";
}

async function main(): Promise<void> {
  const projectDir = readProjectDir(process.argv.slice(2));

  if (!canRenderInk()) {
    console.error("[engine-ui] 当前环境不支持交互式界面（非 TTY）；请用后端裸终端模式。");
    process.exitCode = 2;
    return;
  }

  let connection: Connection | null = null;
  let degradedReason: string | undefined;

  try {
    connection = await connect(
      { projectDir },
      (message) => emitDown(message),
      (reason) => {
        degradedReason = reason;
      },
    );
    if (connection === null) {
      degradedReason = "握手文件未出现（后端未启动或端口发现超时）";
    }
  } catch (error) {
    degradedReason = `连接失败：${(error as Error).message}`;
  }

  try {
    const app = render(
      React.createElement(App, {
        connection,
        ...(degradedReason !== undefined ? { degradedReason } : {}),
      }),
    );
    await app.waitUntilExit();
  } catch (error) {
    // Ink 在非 TTY 下二次抛错时同样退降级，绝不崩栈给用户
    console.error(`[engine-ui] 界面渲染失败：${(error as Error).message}`);
    process.exitCode = 2;
  } finally {
    connection?.close();
  }
}

void main();
