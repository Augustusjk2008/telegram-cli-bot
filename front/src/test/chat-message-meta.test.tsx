import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatMessageMeta } from "../components/ChatMessageMeta";

afterEach(() => {
  vi.useRealTimers();
});

test("shows time only for messages from today", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-08T15:30:00+08:00"));

  render(<ChatMessageMeta name="助手" createdAt="2026-05-08T09:05:00+08:00" />);

  expect(screen.getByText("09:05")).toBeInTheDocument();
  expect(screen.queryByText(/\d{4}\/\d{2}\/\d{2}/)).not.toBeInTheDocument();
});

test("shows date and time for messages from another day", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-08T15:30:00+08:00"));
  const createdAt = "2026-05-07T09:05:00+08:00";
  const createdDate = new Date(createdAt);
  const expectedDate = createdDate.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const expectedTime = createdDate.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  render(<ChatMessageMeta name="助手" createdAt={createdAt} />);

  expect(screen.getByText(`${expectedDate} ${expectedTime}`)).toBeInTheDocument();
});
