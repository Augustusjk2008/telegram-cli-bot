import { expect, test } from "vitest";
import { WORKBENCH_SESSION_VERSION } from "../workbench/workbenchTypes";
import { normalizePersistedWorkbenchSession } from "../workbench/workbenchSession";

test("忽略旧会话中的外部源码标签和活跃令牌，同时保留普通标签", () => {
  const session = normalizePersistedWorkbenchSession({
    version: WORKBENCH_SESSION_VERSION,
    botAlias: "main",
    workspaceRoot: "C:/workspace/main",
    sidebarView: "files",
    activeTabPath: "external-source:src_legacy_token",
    tabs: [
      {
        path: "src/main.py",
        dirty: false,
        savedContent: "print('workspace')\n",
        contentPersistence: "clean_snapshot",
      },
      {
        path: "external-source:src_legacy_token",
        dirty: false,
        savedContent: "print('external')\n",
        contentPersistence: "clean_snapshot",
      },
    ],
  });

  expect(session).toMatchObject({
    activeTabPath: "",
    tabs: [{ path: "src/main.py" }],
  });
  expect(session?.tabs).toHaveLength(1);
});
