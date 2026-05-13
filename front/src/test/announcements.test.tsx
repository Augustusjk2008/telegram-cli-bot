import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { AnnouncementButton } from "../components/AnnouncementButton";
import { AnnouncementDialog } from "../components/AnnouncementDialog";
import type { AnnouncementItem } from "../services/types";

const item: AnnouncementItem = {
  id: "ann-2026-05-13-demo",
  publishedAt: "2026-05-13T09:00:00+08:00",
  publisher: "CLI Bridge",
  title: "公告中心",
  category: "feature",
  severity: "info",
  summary: "公告摘要",
  sections: [{ label: "新增", items: ["自动提醒"] }],
};

test("announcement button shows unread dot", () => {
  render(<AnnouncementButton hasUnseen onClick={() => {}} />);

  expect(screen.getByLabelText("公告")).toBeInTheDocument();
  expect(screen.getByTestId("announcement-unseen-dot")).toBeInTheDocument();
});

test("announcement dialog renders timeline and closes", () => {
  const onClose = vi.fn();

  render(<AnnouncementDialog open items={[item]} latestId={item.id} onClose={onClose} />);

  const dialog = screen.getByRole("dialog", { name: "公告" });
  expect(dialog).toHaveClass("overflow-hidden");
  expect(screen.getByText("公告中心")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));

  expect(onClose).toHaveBeenCalledWith(item.id);
});

test("announcement dialog renders safe inline html", () => {
  const richItem: AnnouncementItem = {
    ...item,
    summary: `<span style="color: red; position: fixed;" onclick="alert(1)">这是红色文字</span><img src=x onerror=alert(1)><script>bad()</script>`,
    sections: [{ label: "新增", items: [`支持 <span style="color: #2563eb;">蓝色</span> 条目`] }],
  };

  const { container } = render(<AnnouncementDialog open items={[richItem]} latestId={richItem.id} onClose={() => {}} />);

  const redText = screen.getByText("这是红色文字");
  expect(redText.tagName.toLowerCase()).toBe("span");
  expect(redText).toHaveStyle({ color: "rgb(255, 0, 0)" });
  expect(redText).not.toHaveAttribute("onclick");
  expect(redText).not.toHaveStyle({ position: "fixed" });
  expect(container.querySelector("img")).toBeNull();
  expect(screen.queryByText("bad()")).not.toBeInTheDocument();
  expect(screen.getByText("蓝色")).toHaveStyle({ color: "rgb(37, 99, 235)" });
});

test("announcement dialog shows empty state", () => {
  render(<AnnouncementDialog open items={[]} latestId="" onClose={() => {}} />);

  expect(screen.getByText("暂无公告")).toBeInTheDocument();
});
