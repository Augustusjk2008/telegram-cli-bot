# 主题工作流

按主题变更的真实范围执行。普通预置主题的变更路径应保持短；只有改变目录、资源或运行时契约时才扩大范围。

## 1. 确定变更类型

先回答三个问题：

1. 这是编辑已有发布预置、添加新的发布预置，还是改变运行时主题管理？
2. 新主题是否只使用现有颜色 token 和现有插画组？
3. 是否需要改变 token、surface、插画资源格式或公共 API？

编辑/添加发布预置属于发布数据变更。开放运行时自定义主题属于产品行为变更，因为当前后端的 `create`、`import_themes`、`update`、`delete` 和上传路由都会返回 `theme_readonly`；不要在普通配色请求中启用它。

## 2. 读取基线并选择最小修改面

先读取当前的 `bot/web/theme_presets.json`、相关 token 和相关插画场景。复制最接近目标的现有主题对象，保留完整的 `appearance` 结构，再逐项修改颜色、排版或插画引用。不要从空对象开始拼主题，也不要因为某个组件暂时没有使用某 token 就删掉它。

普通主题变更的最小文件通常是：

- `bot/web/theme_presets.json`
- 受清单身份影响的后端/前端测试
- `README.md` 和 `README.en.md` 中列出主题名称或只读行为的段落

只要使用已有插画组，就不改 `theme_illustrations.json`、静态资源、后端 set ID 常量或前端插画注册表。

## 3. 编辑现有发布预置

编辑现有主题时：

1. 保持主题 `id` 不变，保持 `baseId: "paper-daylight"`、`schemaVersion: 1` 和 `readonly: true` 不变。
2. 只改需要改变的 `appearance` 字段；`colors.overrides` 使用目录中的真实 token key。
3. 颜色优先使用八位大写十六进制；不透明 token 使用 `FF` alpha。对于能从目录 `derive` 得到的值，只有在主题确实需要不同结果时才写 override。
4. 插画层直接复制目录里的元数据，不能手写一个与 catalog 哈希或尺寸不一致的资源描述。
5. 内容改变时递增 `version`，用 UTC ISO 时间更新 `updatedAt`；不要改 ID 来规避版本变化。
6. 保持主题列表顺序有意且稳定，默认 `paper-daylight` 仍在首位。

## 4. 添加新的发布预置

如果新主题只使用现有 token 和插画组：

1. 从已有主题复制完整对象。
2. 生成稳定且未使用的 `theme_` 加 32 位小写十六进制 ID。
3. 设置新名称、配色模式、颜色覆盖、排版和三个 surface 的插画场景。
4. 保持 `readonly: true`，将主题放在 `themes` 数组的明确位置。
5. 不在 `front/src/theme.ts` 里追加登录页主题常量；登录页通过公共主题 API 读取发布清单，默认回退仍由 `paper-daylight` 提供。
6. 更新所有写死三套主题名称、数量或 ID 的稳定断言和 README 文案。

新主题若使用已有插画组，完成这一步就足够进入验证；不要为每个主题复制一套静态图片。

## 5. 添加或替换内置插画

只有在主题需要新的资源组或现有资源内容改变时执行这一步：

1. 将实际资源放入 `front/public/assets/theme-illustrations/<set-id>/<surface>/`，路径命名与 catalog 一致。当前后端校验发布 catalog 的资源路径为 `.webp`。
2. 计算每个文件的 MIME、像素尺寸和 SHA-256，写入 `bot/web/theme_illustrations.json` 的对应 layer。`assetId`、路径、哈希、尺寸和文件内容必须完全对应。
3. 为新组在三个 surface 都提供至少一个图层；图层 ID 在各自场景内唯一，布局值满足主题规范范围。
4. 在 `bot/web/theme_store.py` 的 `_ILLUSTRATION_SET_IDS` 中加入新 ID；在 `front/src/theme/types.ts` 的联合类型和 `front/src/theme/illustrationPresets.ts` 的 set ID、选项、模板数组中加入同一 ID。更新显示标签和颜色模板时保持命名一致。
5. 将新组引用到 `theme_presets.json`，并增加针对资源路径或场景解析的聚焦测试。
6. 替换现有资源时保留 asset ID 规则并同步更新哈希、尺寸和受影响的预置主题；不要让旧主题继续声明旧元数据。

如果只是把现有主题切换到已有组，跳过本节的注册表和资源工作。

## 6. 修改颜色目录或主题契约

新增/删除 token、CSS 变量、surface 或解析规则会影响所有主题：

- 先检查 `theme_catalog.json` 的 `derive` 依赖、alpha 规则、对比度目标和 `terminal` 标记。
- 再检查 `resolveAppearance.ts`、`AppearanceProvider.tsx`、主题管理器、组件 CSS 和终端映射的消费者。
- 如果新增 surface 或插画字段，同时更新后端规范化、前端类型、解析器、默认值、导入迁移和测试。
- 对现有主题保留兼容默认值；如果必须提高 `schemaVersion`，设计显式迁移并一起更新所有读写端。

这类任务不再是单纯的 `theme_presets.json` 编辑，应按跨模块契约变更验证。

## 7. 验证

先做便宜的静态检查，再运行聚焦测试：

1. 解析 `bot/web/theme_catalog.json`、`bot/web/theme_illustrations.json` 和 `bot/web/theme_presets.json`，确认 JSON 格式有效、主题 ID 唯一、默认主题存在、每个主题的内置 asset ID 都能在插画目录中找到。
2. 对涉及后端数据或只读边界的变更运行：

   ```powershell
   python -m pytest tests/test_theme_store.py tests/test_theme_api.py -q
   ```

   如果本机已提交的存储定位器与仓库测试 fixture 的临时 `TCB_DATA_DIR` 冲突，保留定位器不做迁移或删除；对不依赖公共 fixture 的这两个主题测试可以使用 `python -m pytest --noconftest tests/test_theme_store.py tests/test_theme_api.py -q` 作为受限 fallback，并在交付说明中写明。

3. 对涉及前端解析、客户端、管理器或插画的变更，在 `front` 目录运行：

   ```powershell
   npm exec vitest run src/test/theme.test.ts src/test/theme-client.test.ts src/test/theme-illustrations.test.tsx src/test/theme-manager.test.tsx -- --maxWorkers=1 --fileParallelism=false
   npm run lint
   npm run build
   ```

   如果命令行版本不接受额外的 Vitest 参数，直接运行 `npm run test:gate`，并报告实际命令和结果。

4. 如果变更了布局、插画可见区域或资源加载，使用用户已经启动的应用运行对应 Playwright 检查；不要由 agent 启动开发服务、preview 或临时 HTTP 服务。
5. 最后运行 `git diff --check`，检查 JSON diff 中没有意外删除 token、主题或资源引用，并确认 `front/dist` 等生成物是否属于当前仓库约定。

主题文案或 JSON 机械调整不需要新增测试。新增主题身份、插画路径、资产完整性、只读边界和解析行为属于稳定契约，应更新或保留最合适的一层测试，避免在组件、页面和 shell 层重复断言。

## 8. 交付说明

交付时说明当前有效的主题清单变化、修改的源文件、实际运行的测试/构建命令及结果。若没有运行浏览器检查，指出布局或资源加载边界仍未覆盖；不要把未完成的运行时主题 CRUD 说成已支持。
