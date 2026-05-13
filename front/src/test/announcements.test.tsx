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

test("announcement dialog shows empty state", () => {
  render(<AnnouncementDialog open items={[]} latestId="" onClose={() => {}} />);

  expect(screen.getByText("暂无公告")).toBeInTheDocument();
});
