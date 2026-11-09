import { expect, test } from "@playwright/test";

// Run against a user-started service with PLAYWRIGHT_BASE_URL set.
test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the real API client");

const TOKEN = "ghp_playwrightTokenValue0000000000000000";

for (const width of [1280, 390]) {
  test(`GitHub connection, repository creation and branch publishing fit the Git panel at ${width}px`, async ({ page }) => {
    const root = "/work/demo";
    const bot = { alias: "main", cli_type: "codex", status: "running", working_dir: root };
    let remotes: Array<Record<string, unknown>> = [];
    let upstream = "";
    let account: Record<string, unknown> = {
      connected: false,
      device_flow_available: true,
      token_create_url: "https://github.com/settings/tokens/new?scopes=repo,read:org",
      required_scopes: ["repo", "read:org"],
    };
    const calls: string[] = [];
    const overview = () => ({
      repo_found: true, can_init: false, working_dir: root, repo_path: root, repo_name: "demo",
      current_branch: "main", is_clean: true, ahead_count: 0, behind_count: 0, changed_files: [],
      changed_files_truncated: false, changed_files_total_estimate: 0, status_truncated: false,
      untracked_files_truncated: false, count_lower_bound: 0, count_exact: true, truncation_reason: "",
      recent_commits: [{ hash: "abc1234", short_hash: "abc1234", subject: "Initial commit", author_name: "Dev", authored_at: "2026-11-09" }],
    });
    const remoteList = () => ({
      repo_found: true, working_dir: root, repo_path: root, current_branch: "main",
      upstream, has_commits: true, remotes, github_account_auth: true,
    });
    const capabilities = () => {
      const hasRemote = remotes.length > 0;
      const entry = (available: boolean, reason = "") => ({ available, reason: available ? "" : reason, requires_confirmation: false });
      return {
        capabilities: {
          tree_status: entry(true), commit_graph: entry(true), branches: entry(true), branch_mutation: entry(true),
          discard: entry(true), stash: entry(true), stash_create: entry(true), identity: entry(true),
          fetch: entry(hasRemote, "git_remote_not_configured"),
          pull: entry(Boolean(upstream), "git_upstream_not_configured"),
          push: entry(Boolean(upstream), "git_upstream_not_configured"),
          remotes: entry(true),
          publish: entry(hasRemote, "git_remote_not_configured"),
          commit_message_generation: entry(true), smart_commit: entry(true),
        },
      };
    };

    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.split("/api/")[1];
      const method = request.method();
      let data: unknown = {};
      if (path === "auth/me") {
        data = { is_logged_in: true, username: "qa", account_id: "qa", role: "member", current_bot_alias: "main", capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send", "git_ops"] };
      } else if (path === "bots") data = [bot];
      else if (path === "bots/main") data = { bot, session: { working_dir: root, is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
      else if (path === "bots/main/ls") data = { working_dir: root, entries: [] };
      else if (path === "bots/main/pwd") data = { working_dir: root };
      // The desktop shell mounts the terminal pane, which needs a well-formed actions list.
      else if (path === "bots/main/terminal-actions/config") data = { schemaVersion: 1, actions: [], configPath: "", exists: false, mtimeNs: "0", editable: false, errors: [], runtimePlatform: "linux" };
      else if (path === "github/account" && method === "GET") data = account;
      else if (path === "github/account/token") {
        calls.push("connect");
        expect(request.postDataJSON()).toEqual({ token: TOKEN });
        account = { ...account, connected: true, login: "octocat", name: "Mona", html_url: "https://github.com/octocat", auth_method: "token", token_kind: "classic", scopes: ["repo", "read:org"] };
        data = account;
      } else if (path === "github/owners") data = { items: [{ login: "octocat", type: "user" }, { login: "acme", type: "org" }] };
      else if (path === "github/repos" && method === "POST") {
        const body = request.postDataJSON();
        calls.push(`create ${body.owner}/${body.name} private=${body.private}`);
        data = {
          id: 7, name: body.name, full_name: `${body.owner}/${body.name}`, owner: body.owner, private: body.private,
          html_url: `https://github.com/${body.owner}/${body.name}`,
          clone_url: `https://github.com/${body.owner}/${body.name}.git`,
          ssh_url: `git@github.com:${body.owner}/${body.name}.git`, can_push: true,
        };
      } else if (path === "bots/main/git/capabilities") data = capabilities();
      else if (path === "bots/main/git/remotes") {
        if (method === "POST") {
          const body = request.postDataJSON();
          calls.push(`remote add ${body.name} ${body.url}`);
          remotes = [{
            name: body.name, fetch_url: body.url, push_url: body.url, protocol: "https", has_embedded_credentials: false,
            github: { owner: "acme", repo: "demo", full_name: "acme/demo", html_url: "https://github.com/acme/demo", protocol: "https" },
          }];
        }
        data = remoteList();
      } else if (path === "bots/main/git/publish") {
        calls.push(`publish ${request.postDataJSON().remote}`);
        upstream = "origin/main";
        data = { message: "已发布当前分支并设置 upstream", overview: overview() };
      } else if (path.startsWith("bots/main/git")) {
        const operation = path.slice("bots/main/git".length);
        if (operation === "/tree-status") data = { repo_found: true, working_dir: root, repo_path: root, items: {} };
        else if (operation === "/branches") data = { current_branch: "main", branches: [{ name: "main", current: true, upstream, short_hash: "abc1234", subject: "Initial commit" }] };
        else if (operation === "/graph") data = { repo_found: true, scope: "all", nodes: [], has_more: false, next_cursor: "" };
        else if (operation === "/stashes") data = { items: [] };
        else if (operation === "/identity") data = { repo_found: true, repo_path: root, global: { name: "Dev", email: "dev@example.com" }, local: { name: "", email: "" } };
        else if (operation === "/commit-message/config") data = { cli_type: "codex", cli_path: "codex", params: {}, defaults: {}, schema: {} };
        else if (operation === "/smart-commit/active") data = null;
        else data = overview();
      } else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
      else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
      else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
      else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
      await route.fulfill({ json: { ok: true, data } });
    });

    page.on("dialog", (dialog) => dialog.accept());
    await page.setViewportSize({ width, height: 900 });
    await page.goto("./");
    await page.getByRole("button", { name: "Git", exact: true }).click();

    const remotesPanel = page.getByTestId("git-remotes-panel");
    await expect(remotesPanel.getByText("main 尚未设置 upstream")).toBeVisible();
    await remotesPanel.getByRole("button", { name: "关联 GitHub 仓库" }).first().click();
    const linkPanel = page.getByTestId("git-github-link-panel");
    await linkPanel.getByRole("textbox", { name: "GitHub 个人访问令牌" }).fill(TOKEN);
    await linkPanel.getByRole("button", { name: "连接", exact: true }).click();
    await expect(linkPanel.getByRole("option", { name: "acme（组织）" })).toBeAttached();
    await linkPanel.getByLabel("仓库所有者").selectOption("acme");
    await expect(linkPanel.getByLabel("新仓库名称")).toHaveValue("demo");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`github-link-form-${width}.png`) });

    await linkPanel.getByRole("button", { name: "创建并关联" }).click();
    await expect(remotesPanel.getByText("已创建并关联 acme/demo 为远端 origin，并发布分支 main")).toBeVisible();
    await expect(remotesPanel.getByText("main → origin/main")).toBeVisible();
    await expect(page.getByTestId("git-remote-row-origin")).toContainText("HTTPS 使用 GitHub 账号 @octocat");
    await expect(page.getByRole("button", { name: "Push", exact: true })).toBeEnabled();
    expect(calls).toEqual([
      "connect",
      "create acme/demo private=true",
      "remote add origin https://github.com/acme/demo.git",
      "publish origin",
    ]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`github-linked-${width}.png`) });
  });
}
