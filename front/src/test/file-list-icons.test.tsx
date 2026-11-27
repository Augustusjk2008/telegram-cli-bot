import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FileList } from "../components/FileList";

test("portrait rows use desktop icons, including fallbacks for names matching object properties", () => {
  const files = [
    { name: "src", isDir: true },
    { name: "main.py", isDir: false },
    { name: "constructor", isDir: true },
    { name: "report.__proto__", isDir: false },
  ];
  render(<FileList files={files} onDirClick={vi.fn()} onFileClick={vi.fn()} />);

  const icon = (name: string) => screen.getByRole("button", { name }).querySelector("[data-icon]");
  expect(icon("进入 src")).toHaveAttribute("data-folder-kind", "src");
  expect(icon("打开 main.py")).toHaveAttribute("data-icon", "file-python");
  expect(icon("进入 constructor")).toHaveAttribute("data-folder-kind", "default");
  expect(icon("打开 report.__proto__")).toHaveAttribute("data-icon", "file-generic");
});
