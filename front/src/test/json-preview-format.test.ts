import { expect, test } from "vitest";
import { formatJsonPreview, JSON_PREVIEW_MAX_BYTES } from "../utils/jsonPreview";

test("嵌套对象和数组使用两空格缩进，空容器保持紧凑", () => {
  const content = ' \r\n{ "items" : [1,{"empty": { \t }, "list": [\r\n]}], "enabled":true }\t';
  expect(formatJsonPreview(content, true)).toEqual({
    status: "formatted",
    content: '{\n  "items": [\n    1,\n    {\n      "empty": {},\n      "list": []\n    }\n  ],\n  "enabled": true\n}',
  });
});

test.each(["{}", "[]", "null", "true", "false", "-0", '"文字  😀"'])("支持顶层 JSON 值 %s", (content) => {
  expect(formatJsonPreview(` \t${content}\r\n`, true)).toEqual({ content, status: "formatted" });
});

test("保留键顺序、重复键、长整数、数字字面量及字符串原始转义", () => {
  const content = String.raw`{"10":1,"2":2,"dup":90071992547409931234567890,"dup":-0,"n":1.2300e+04,"exp":1E400,"text":"a  { } [ ] , : \" \\ \/ \b \f \n \r \t \u4e2D \uD83D\uDE00","tail":"ends with \\"}`;
  expect(formatJsonPreview(content, true)).toEqual({
    status: "formatted",
    content: String.raw`{
  "10": 1,
  "2": 2,
  "dup": 90071992547409931234567890,
  "dup": -0,
  "n": 1.2300e+04,
  "exp": 1E400,
  "text": "a  { } [ ] , : \" \\ \/ \b \f \n \r \t \u4e2D \uD83D\uDE00",
  "tail": "ends with \\"
}`,
  });
});

test.each([
  '{"a":1,}',
  '{/* comment */"a":1}',
  '{"a":1}\n{"b":2}',
  "NaN",
  "01",
  '"unescaped\nnewline"',
  String.raw`"\x41"`,
  " \t\r\n",
  "\ufeff{}",
])("非标准或无效 JSON 回退原文：%j", (content) => {
  expect(formatJsonPreview(content, true)).toEqual({ content, status: "invalid" });
});

test("未完整读取时不格式化合法片段，空内容仅在完整读取时视为空文件", () => {
  const content = ' {"a":1} ';
  expect(formatJsonPreview(content, false)).toEqual({ content, status: "incomplete" });
  expect(formatJsonPreview("", false)).toEqual({ content: "", status: "incomplete" });
  expect(formatJsonPreview("", true)).toEqual({ content: "", status: "empty" });
});

test("按 UTF-8 字节限制输出，恰好 4 MiB 可用，超出时保留原文", () => {
  const unit = "é中😀\ud800";
  const unitBytes = 12;
  const bodyBytes = JSON_PREVIEW_MAX_BYTES - 2;
  const body = unit.repeat(Math.floor(bodyBytes / unitBytes)) + "a".repeat(bodyBytes % unitBytes);
  const atLimit = `"${body}"`;
  expect(new TextEncoder().encode(atLimit).byteLength).toBe(JSON_PREVIEW_MAX_BYTES);
  expect(formatJsonPreview(atLimit, true).status).toBe("formatted");
  const overLimit = `"${body}a"`;
  expect(formatJsonPreview(overLimit, true)).toEqual({ content: overLimit, status: "too-large" });
});

test("极深嵌套在缩进膨胀超限时停止并回退，不递归或生成全部缩进", () => {
  const depth = 50_000;
  const content = "[".repeat(depth) + "0" + "]".repeat(depth);
  expect(formatJsonPreview(content, true)).toEqual({ content, status: "too-large" });
});
