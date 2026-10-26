/**
 * 入口降级判定（片 4）：非 TTY 环境下前端必须优雅退出，不得崩栈。
 * `engine` 依赖"退出码 2"识别降级并回落裸终端。
 */

import { describe, expect, it } from "vitest";

import { canRenderInk } from "../src/main.js";

describe("canRenderInk（非 TTY 降级判定）", () => {
  it("普通管道流（无 isTTY / 无 setRawMode）→ false", () => {
    const stream = {} as unknown as NodeJS.ReadStream;
    expect(canRenderInk(stream)).toBe(false);
  });

  it("isTTY=true 但无 setRawMode → false（Windows 管道特征）", () => {
    const stream = { isTTY: true } as unknown as NodeJS.ReadStream;
    expect(canRenderInk(stream)).toBe(false);
  });

  it("isTTY=true 且有 setRawMode → true（真实终端）", () => {
    const stream = {
      isTTY: true,
      setRawMode: () => undefined,
    } as unknown as NodeJS.ReadStream;
    expect(canRenderInk(stream)).toBe(true);
  });

  it("isTTY=false 即便有 setRawMode → false", () => {
    const stream = {
      isTTY: false,
      setRawMode: () => undefined,
    } as unknown as NodeJS.ReadStream;
    expect(canRenderInk(stream)).toBe(false);
  });
});
