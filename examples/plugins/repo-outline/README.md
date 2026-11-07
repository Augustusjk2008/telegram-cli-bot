# Repo Outline

Repo Outline 在当前 Bot 的本地工作区中浏览目录、代码文件和符号。它通过 Host API 读取工作区，不会修改文件；远程工作区目前不支持插件视图。

## 安装

在仓库根目录，用运行 Orbit 的同一个 Python 解释器执行：

```bash
python -m bot.plugins.installer --repo-root . --plugin repo-outline
```

也可以在 Web 的“插件”页面点击“安装插件”，选择包含 `repo-outline/plugin.json` 的插件父目录，然后刷新插件列表。

## 使用

1. 打开“插件”页面，找到 **Repo Outline**。
2. 点击“选择文件夹大纲”，选择当前 Bot 工作区中的目录。
3. 点击文件夹左侧的 `+` 展开目录；点击文件左侧的 `+` 加载该文件的符号。
4. 点击文件名可打开文件，点击“跳到定义”可定位到符号所在行。
5. 使用搜索框查找目录名、文件名或符号；“刷新”会重新扫描，“折叠全部”会收起树节点。

## 设置

插件卡片的“设置”中可以调整：

- `包含隐藏目录`
- `忽略目录名（逗号分隔）`
- `最大扫描文件数`
- `单文件最大符号数`
- `代码扩展名`

默认忽略 `.git`、`node_modules`、虚拟环境、缓存、`dist` 和 `build`，默认解析 Python、TypeScript、JavaScript、Go、Rust、Java、Kotlin、Markdown 和 C++ 文件。

扫描或搜索达到上限时，视图顶部会显示截断提示。Repo Outline 使用 Python AST、Markdown 标题和通用代码模式提取符号，不等同于完整的语言服务器索引。
