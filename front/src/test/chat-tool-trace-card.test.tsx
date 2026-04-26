import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { ChatToolTraceCard } from "../components/ChatToolTraceCard";
import type { ToolGroupChatTraceEntry } from "../utils/chatTraceGrouping";

function createLongApplyPatchEntry(): ToolGroupChatTraceEntry {
  const patch = [
    "*** Begin Patch",
    "*** Update File: demo.txt",
    "@@",
    "-old line 1",
    "+new line 1",
    "+new line 2",
    "+new line 3",
    "+new line 4",
    "+new line 5",
    "+new line 6",
    "+new line 7",
    "*** End Patch",
  ].join("\n");

  return {
    kind: "tool_group",
    toolIndex: 1,
    state: "completed",
    call: {
      kind: "tool_call",
      title: "apply_patch",
      toolName: "apply_patch",
      callId: "call_patch_1",
      summary: patch,
      payload: {
        arguments: patch,
      },
    },
    results: [
      {
        kind: "tool_result",
        callId: "call_patch_1",
        summary: '{"success":true}',
        payload: {
          output: {
            success: true,
          },
        },
      },
    ],
  };
}

describe("ChatToolTraceCard", () => {
  test("collapses long apply_patch call summary by default and expands on demand", async () => {
    const user = userEvent.setup();

    render(<ChatToolTraceCard entry={createLongApplyPatchEntry()} />);
    const callSummary = screen.getByText("调用").nextElementSibling as HTMLElement;

    expect(screen.getByText("工具调用 1")).toBeInTheDocument();
    expect(callSummary.textContent || "").toContain("*** Begin Patch");
    expect(callSummary.textContent || "").not.toContain("+new line 7");
    expect(screen.getByText("成功")).toBeInTheDocument();

    const expandButton = screen.getByRole("button", { name: "展开完整内容" });
    await user.click(expandButton);

    expect(callSummary.textContent || "").toContain("+new line 7");
    expect(screen.getByRole("button", { name: "收起完整内容" })).toBeInTheDocument();
  });
});
