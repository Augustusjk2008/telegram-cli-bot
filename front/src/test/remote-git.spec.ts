import { expect, test } from "@playwright/test";

// Run against a user-started service with PLAYWRIGHT_BASE_URL set.
test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the real API client");

for (const width of [1280, 390]) {
  test(`remote Git supported actions and request boundary at ${width}px`, async ({ page }) => {
    const remote = { connection_id: "ssh-qa", host: "linux.test", port: 22, username: "dev", root: "/srv/project", host_key_fingerprint: "SHA256:qa" };
    const bot = { alias: "remote", cli_type: "codex", status: "running", working_dir: "C:/control", remote_workspace: remote };
    const changed = (path: string, staged = false, untracked = false) => ({ path, staged, untracked, unstaged: !staged && !untracked, status: untracked ? "??" : staged ? "M " : " M", additions: 1, deletions: 0 });
    let files = [changed("tracked.txt"), changed("staged.txt", true), changed("new.txt", false, true)];
    let subject = "Remote initial commit";
    let gitMissing = true;
    const gitRequests: string[] = [];
    const unsupportedRequests: string[] = [];
    const overview = () => ({
      repo_found: true, can_init: false, working_dir: remote.root, repo_path: remote.root,
      repo_name: "project", current_branch: "main", is_clean: files.length === 0,
      ahead_count: 0, behind_count: 0, changed_files: files,
      changed_files_truncated: false, changed_files_total_estimate: files.length,
      status_truncated: false, untracked_files_truncated: false,
      count_lower_bound: files.length, count_exact: true, truncation_reason: "",
      recent_commits: [{ hash: "abc1234", short_hash: "abc1234", subject, author_name: "Dev", authored_at: "2026-09-24" }],
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.split("/api/")[1];
      let data: unknown = {};
      if (path === "auth/me") data = { is_logged_in: true, username: "remote-qa", account_id: "remote-qa", role: "member", current_bot_alias: "remote", capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send", "git_ops"] };
      else if (path === "bots") data = [bot];
      else if (path === "bots/remote") data = { bot, session: { working_dir: "C:/control", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
      else if (path === "bots/remote/ls") data = { working_dir: remote.root, entries: [{ name: "tracked.txt", is_dir: false }] };
      else if (path === "bots/remote/pwd") data = { working_dir: remote.root };
      else if (path.startsWith("bots/remote/git")) {
        const operation = path.slice("bots/remote/git".length);
        gitRequests.push(`${request.method()} ${operation || "/"}`);
        if (!["", "/diff", "/stage", "/unstage", "/commit", "/tree-status", "/branches", "/graph", "/stashes", "/identity"].includes(operation)) {
          unsupportedRequests.push(path);
          await route.fulfill({ status: 501, json: { ok: false, error: { code: "remote_feature_unavailable", message: "Unsupported remote Git operation" } } });
          return;
        }
        if (!operation && gitMissing) {
          gitMissing = false;
          await route.fulfill({ status: 503, json: { ok: false, error: { code: "remote_git_not_found", message: "Git unavailable" } } });
          return;
        }
        if (operation === "/tree-status") data = { repo_found: true, working_dir: remote.root, repo_path: remote.root, items: { "tracked.txt": "modified", "new.txt": "added" } };
        else if (operation === "/branches") data = { current_branch: "main", branches: [{ name: "main", current: true, upstream: "origin/main", short_hash: "abcdef1", subject: "Remote graph title" }] };
        else if (operation === "/graph") data = { repo_found: true, scope: url.searchParams.get("scope") || "all", nodes: [{ hash: "abcdef1234567890", short_hash: "abcdef1", parents: [], author_name: "Dev", authored_at: "2026-09-24T12:00:00Z", subject: "Remote graph title", message: "Remote graph title\n\nComplete remote commit message.", refs: [{ name: "main", kind: "local_branch", current: true }], graph: { column: 0, width: 1, edges: [] } }], has_more: false, next_cursor: "" };
        else if (operation === "/stashes") data = { items: [{ ref: "stash@{0}", hash: "stash123", created_at: "2026-09-24", message: "Remote stash" }] };
        else if (operation === "/identity") data = { repo_found: true, repo_path: remote.root, global: { name: "Remote Dev", email: "remote@example.com" }, local: { name: "Repo Dev", email: "repo@example.com" } };
        else if (operation === "/diff") data = { path: url.searchParams.get("path"), staged: url.searchParams.get("staged") === "true", diff: "diff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -0,0 +1 @@\n+remote change", truncated: false };
        else if (operation === "/stage" || operation === "/unstage") {
          const paths = request.postDataJSON().paths as string[];
          expect(paths).toHaveLength(1);
          files = files.map((file) => paths.includes(file.path) ? changed(file.path, operation === "/stage") : file);
          data = { message: "Index updated", overview: overview() };
        } else if (operation === "/commit") {
          subject = request.postDataJSON().message;
          files = [];
          data = { message: "Committed", overview: overview() };
        } else data = overview();
      }
      else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
      else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
      else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
      else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
      if (path.includes("rollback")) unsupportedRequests.push(path);
      await route.fulfill({ json: { ok: true, data } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("./");
    await expect(page.getByRole("button", { name: "SSH 连接", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Git", exact: true }).click();
    const guidance = page.getByRole("alert");
    await expect(guidance).toContainText("非交互式 PATH");
    await expect(guidance.getByRole("link", { name: "Linux 官方安装指南" })).toBeVisible();
    await expect(guidance.getByRole("link", { name: "Windows 官方安装指南" })).toBeVisible();
    await guidance.getByRole("button", { name: "重试" }).click();
    await expect(page.getByText("Remote initial commit", { exact: true })).toBeVisible();
    await expect(page.getByText(/origin\/main/)).toBeVisible();
    await expect(page.getByText("Remote stash", { exact: true })).toBeVisible();
    await expect(page.getByText(/Complete remote commit message\./)).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Git 用户名", exact: true })).toHaveValue("Remote Dev");
    await expect(page.getByRole("button", { name: /切换|新建分支|应用 stash|删除 stash|Fetch|Pull|Push|保存 Git 用户|初始化 Git 仓库|重置到此提交|智能提交/ })).toHaveCount(0);
    for (const path of ["staged.txt", "tracked.txt", "new.txt"]) {
      await page.getByRole("button", { name: `打开 diff ${path}`, exact: true }).click();
      if (width === 1280) await expect(page.getByRole("tab", { name: `${path}.diff`, exact: true })).toBeVisible();
      else await expect(page.getByTestId("git-diff-content")).toContainText("remote change");
    }
    await page.getByRole("button", { name: "暂存 tracked.txt", exact: true }).click();
    await expect(page.getByRole("button", { name: "取消暂存 tracked.txt", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "取消暂存 tracked.txt", exact: true }).click();
    await expect(page.getByRole("button", { name: "暂存 tracked.txt", exact: true })).toBeEnabled();
    await page.getByRole("textbox", { name: "commit message", exact: true }).fill("Manual remote commit");
    await page.getByRole("button", { name: "提交更改", exact: true }).click();
    await expect(page.getByText("Manual remote commit", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /丢弃|暂存全部|初始化|新建分支|Fetch|Pull|Push|智能提交|生成|重置到此提交/ })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`remote-git-${width}.png`) });
    await page.getByRole("button", { name: "文件", exact: true }).click();
    await expect(page.getByRole("button", { name: "打开 tracked.txt", exact: true })).toBeVisible();
    expect(gitRequests).toEqual(expect.arrayContaining(["GET /", "GET /tree-status", "GET /branches", "GET /graph", "GET /stashes", "GET /identity", "GET /diff", "POST /stage", "POST /unstage", "POST /commit"]));
    expect(unsupportedRequests).toEqual([]);
  });
}
