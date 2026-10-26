/**
 * 中文字宽（spec『外观与分发』：中文列宽按东亚字符宽度计算）。
 *
 * 红线：**不得用 String.length** 计算列宽——全角字符占 2 列，用 length 会让
 * 面板与表格错位。
 */

import { eastAsianWidth } from "get-east-asian-width";

/** 单个码点的显示宽度（eastAsianWidth 直接返回 1 或 2）。 */
function charWidth(char: string): number {
  const codePoint = char.codePointAt(0);
  if (codePoint === undefined) return 0;
  return eastAsianWidth(codePoint, { ambiguousAsWide: false });
}

/** 一段文本的显示宽度（列数）。 */
export function displayWidth(text: string): number {
  let width = 0;
  for (const char of text) {
    width += charWidth(char);
  }
  return width;
}

/** 按显示宽度左对齐填充（不足补空格）。 */
export function padEndWidth(text: string, targetWidth: number): string {
  const pad = targetWidth - displayWidth(text);
  return pad > 0 ? text + " ".repeat(pad) : text;
}
