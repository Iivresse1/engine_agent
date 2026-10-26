/**
 * 前端入口（UX-3 片 2）：连后端 → 渲染 Ink 界面；连不上退降级提示。
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

async function main(): Promise<void> {
  const projectDir = readProjectDir(process.argv.slice(2));
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

  const app = render(
    React.createElement(App, {
      connection,
      ...(degradedReason !== undefined ? { degradedReason } : {}),
    }),
  );

  await app.waitUntilExit();
  connection?.close();
}

void main();
