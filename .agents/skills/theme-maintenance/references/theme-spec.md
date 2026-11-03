# 主题规范

本文档描述当前代码已经实现的主题契约。精确的 token、插画资产 ID、尺寸和哈希以仓库中的 JSON 文件为准；这里记录结构、边界和容易遗漏的关联。

## 主题系统边界

当前发布包包含五套只读预置主题，顺序和身份如下：

| ID | 名称 | 角色 | 当前插画组 |
| --- | --- | --- | --- |
| `paper-daylight` | 钢铁核心 | 默认主题，保留这个 ID | `armor-core-hud` |
| `theme_0f2e4a8c1d6b4f90a3c7e5b2d8f1046a` | 阿波罗计划 | 发布预置 | `apollo-plan` |
| `theme_92ba863d3714c089235dfcef47ce3415` | 薄荷柑橘 | 发布预置 | `mint-citrus` |
| `theme_3dc3829743be9c6941e6da88c0f780a1` | 赛博朋克 | 发布预置 | `cyberpunk-2077` |
| `theme_6f7ac1823da81d2e52d1a1549ee69c85` | Deepseek | 发布预置 | `deepseek-big-fish` |

每套发布预置都具有 `schemaVersion: 1`、`baseId: "paper-daylight"` 和 `readonly: true`。默认主题应保持在主题列表首位。新增主题时先读取 `bot/web/theme_presets.json`，不要把上表的数量当成永远不变的常量。

全局主题库通过 `/api/public/ui/themes` 和 `/api/ui/themes` 读取。登录页只在当前浏览器保存预览选择；登录后的选中主题在账户之间共享保存。运行时持久化的是选中 ID 和 revision。当前 `bot/web/theme_store.py` 以及主题路由会拒绝主题创建、导入、更新、删除和资源上传，返回只读错误；主题包内的预置内容仍由版本文件提供。

## 源文件和消费者

| 文件 | 作用 | 什么时候修改 |
| --- | --- | --- |
| `bot/web/theme_presets.json` | 发布主题清单和每套主题的完整外观 | 添加或编辑发布预置 |
| `bot/web/theme_catalog.json` | `schemaVersion: 1` 的颜色 token 目录；当前有 298 个 token | 增加/删除 token、CSS 变量或 token 语义 |
| `bot/web/theme_illustrations.json` | `schemaVersion: 3` 的内置插画组、三类 surface、图层元数据和资源路径 | 添加/替换内置插画资产 |
| `front/public/assets/theme-illustrations/` | 与插画目录路径对应的静态资源 | 添加/替换内置插画文件 |
| `front/src/theme/resolveAppearance.ts` | 前端外观规范化、派生颜色解析、插画解析和对比度计算 | 只有主题契约或解析行为改变时修改 |
| `front/src/theme/types.ts` | 主题结构、surface、插画组和资源类型 | 新增 surface 或插画组类型时修改 |
| `front/src/theme/illustrationPresets.ts` | 插画组 ID、显示选项、模板和 catalog 映射 | 新增插画组或编辑主题管理器选项时修改 |
| `bot/web/theme_store.py` | 后端 token、插画、主题文件校验和全局 selection 持久化 | 后端契约改变，或新增插画组需要加入允许列表时修改 |
| `tests/test_theme_store.py`、`tests/test_theme_api.py` | 后端主题数据和 API 契约 | 清单身份、只读边界或资源契约改变时更新 |
| `front/src/test/theme*.test.ts*` | 前端解析、客户端、插画和管理器契约 | 受影响的前端行为改变时更新 |

普通预置主题只需要改 `theme_presets.json`；它使用现有 token 和插画组时不需要改解析器、类型或注册表。

## 主题对象

发布文件的根形状是：

```json
{
  "schemaVersion": 1,
  "scope": "global",
  "revision": 0,
  "selectedThemeId": "paper-daylight",
  "themes": [
    {
      "schemaVersion": 1,
      "id": "theme_<32 位小写十六进制>",
      "name": "主题名称",
      "baseId": "paper-daylight",
      "appearance": {
        "colors": {
          "scheme": "light",
          "overrides": {}
        },
        "typography": {
          "chatBodyFontFamily": "sans",
          "chatBodyFontSize": "medium",
          "chatBodyLineHeight": "normal",
          "chatBodyParagraphSpacing": "normal"
        },
        "illustrations": {}
      },
      "readonly": true,
      "updatedAt": "2026-01-01T00:00:00Z",
      "version": 1
    }
  ]
}
```

示例中的 `illustrations` 只是占位，发布主题必须使用完整的规范化场景配置。新主题 ID 应稳定且唯一，格式为 `theme_` 加 32 位小写十六进制；`paper-daylight` 是保留的默认 ID。不要通过改名或复用旧 ID 生成一个看似全新的主题，否则已经保存的全局选择会指向另一个外观。

`name` 经过后端校验后必须是 1 到 80 个字符，不能包含控制字符。`updatedAt` 必须是包含时区的 ISO 时间字符串，`version` 是至少为 1 的整数。主题的 `baseId` 当前固定为 `paper-daylight`，`schemaVersion` 当前固定为 1。

## 颜色契约

`appearance.colors` 只能包含 `scheme` 和 `overrides`。`scheme` 为 `light` 或 `dark`；`overrides` 的 key 必须来自 `theme_catalog.json`。

- 颜色接受 `#RGB`、`#RGBA`、`#RRGGBB` 或 `#RRGGBBAA`，后端会规范化成大写的八位格式。
- token 的 `allowAlpha: false` 时必须使用完全不透明的颜色；只有目录允许透明度时才能使用 alpha。
- 未写入 `overrides` 的 token 使用目录的 `derive` 或 `default`。派生 token 依赖的 key 必须存在，不能循环依赖。
- `cssVariable` 存在时会写入对应的 CSS 自定义属性；没有 `cssVariable` 的 token 仍可能被组件直接读取，不能因为没有 CSS 变量就删除。
- `contrastAgainst` 和 `minContrast` 描述文字、焦点、边框等 token 的最低对比度目标。颜色编辑后检查主题管理器的对比度提示，并覆盖工作台、聊天、编辑器、终端、文件树、状态反馈和弹层等场景。
- `terminal` 标记的 token 会生成终端主题。至少检查终端前景、光标、选区前景与选区背景的可读性；现有测试把 4.5 作为终端基线。

## 排版契约

`appearance.typography` 可以省略；解析器会使用默认值。若提供它，四个字段都必须存在：

- `chatBodyFontFamily`: `sans`、`serif`、`kai`、`fangsong` 或 `mono`
- `chatBodyFontSize`: `small`、`medium` 或 `large`
- `chatBodyLineHeight`: `tight`、`normal` 或 `relaxed`
- `chatBodyParagraphSpacing`: `tight`、`normal` 或 `relaxed`

当前五套发布主题都显式保存默认排版值。编辑主题时保持这四项完整，避免产生依赖隐式默认值的半配置。

## 插画契约

新发布主题使用规范化的 `appearance.illustrations`：

```json
{
  "opacity": 0.12,
  "surfaces": {
    "workbench": true,
    "adminCenter": true,
    "agentManager": true
  },
  "scenes": {
    "workbench": { "layers": [] },
    "adminCenter": { "layers": [] },
    "agentManager": { "layers": [] }
  }
}
```

当前 surface 只有 `workbench`、`adminCenter` 和 `agentManager`，三者都必须出现。每个场景包含 1 到 32 个图层，图层 ID 在场景内唯一。图层必填 `id`、`asset`、`anchor` 和 `enabled`；`anchor` 为 `top`、`left`、`right`、`bottom`、`bottom-left`、`bottom-right` 或 `center`。可选的 `x`、`y` 范围为 -100 到 100，`width` 和 `height` 范围为 0.01 到 300，`opacity` 范围为 0 到 1，`objectPosition` 最长 120 个字符。场景总透明度 `opacity` 范围为 0 到 0.25。

内置资源必须来自 `theme_illustrations.json`，并完整匹配其中的 `assetId`、`mimeType`、`width`、`height` 和 `sha256`。资源路径必须与 `front/public/assets/` 下的实际文件对应。上传资源另有单文件 4 MiB、单主题总量 12 MiB 的限制；发布预置不应把上传资源写入主题文件。

当前插画目录有 `none`、`forest-grove`、`tidal-grove`、`desert-dusk`、`alpine-fog`、`moonlit-garden`、`armor-core-hud`、`apollo-plan`、`mint-citrus`、`cyberpunk-2077` 和 `deepseek-big-fish` 十一个组。`none` 是无装饰的基线。插画目录和后端允许列表、前端 `ThemeIllustrationSetId` 联合类型及选项数组必须保持同步。

旧版 `setId`/`upload` 格式仍用于导入和迁移。新发布数据使用 `scenes` 规范，除非任务本身是在维护迁移兼容性，否则不要新增旧格式。
