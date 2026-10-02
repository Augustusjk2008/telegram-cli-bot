# HTML → DOCX

将工作区中的静态 HTML 报告导出为 Word 文档。标题、正文、列表和表格使用 Word 原生对象，可以继续编辑；PNG/JPEG 插图和内联 SVG 图表以静态图片嵌入。转换使用本地 Python 依赖，不需要启动浏览器或安装 Office；最终分页以 Word / LibreOffice 的实际排版为准。

## 安装与使用

在仓库根目录，使用**运行 Orbit 宿主的同一个 Python 解释器**安装插件：

```powershell
python -m bot.plugins.installer --plugin html-docx
```

也可以将整个 `examples/plugins/html-docx/` 目录复制到插件目录，通常为 `~/.tcb/plugins/html-docx/`。必须保留 `backend/`、`requirements.txt`、`plugin.json` 和样例的相对目录结构。安装器默认跳过已安装的插件。

用宿主 Python 安装已安装插件目录中的依赖。例如在 Windows PowerShell 中：

```powershell
& "C:\path\to\host\python.exe" -m pip install -r "C:\path\to\plugins\html-docx\requirements.txt"
```

将示例路径替换成实际路径。缺少依赖时，插件视图会显示包含宿主解释器和插件路径的安装命令，导出不可用；插件不会自动安装依赖。

1. 刷新插件目录，在工作区打开 UTF-8 编码的 `.html` 或 `.htm` 文件，选择 **HTML 转 Word**。
2. 查看报告标题、段落 / 表格 / 图片数量，以及转换提示和错误。先修复阻止导出的错误。
3. 点击 **导出 DOCX** 下载文档。每次导出都会重新读取 HTML 和关联资源，保存修改后再导出即可。
4. 用 Word 或 LibreOffice 打开产物，检查分页、中文换行、表头、合并单元格和插图位置。

体验样例时，将插件中的整个 `samples/` 目录复制到当前工作区，再打开其中的 HTML。不要只复制 HTML，否则相对路径图片会缺失。在仓库本身作为工作区时，也可以直接打开 `examples/plugins/html-docx/samples/` 中的文件。

## 支持的报告内容

| 内容 | 转换结果与编写建议 |
| --- | --- |
| `h1`–`h6`、`p`、`blockquote` | 原生标题、段落和引用，保留文档顺序；标题尽量与后文保持同页 |
| `strong` / `b`、`em` / `i`、`u`、`sub`、`sup`、`br` | 粗体、斜体、下划线、上下标和换行；可在同一段落混用中英文与不同格式 |
| `a` | `http` / `https` / `mailto` / `tel` 超链接和 `#锚点`；链接目标不会被下载。相对文件链接不支持，正文应包含有意义的链接文字 |
| `ul`、`ol`、`li` | 原生项目符号 / 编号列表，支持嵌套；子列表放在所属 `li` 内 |
| `pre`、`code` | 保留代码块必要的空白和换行；过长代码行仍可能超出版心，应主动折行 |
| `table`、`thead`、`tbody`、`tr`、`th`、`td` | 可编辑表格，支持列宽、边框、底色、对齐、`rowspan` / `colspan`；给出明确且一致的列宽 |
| `img` | 工作区内相对路径或 data URI 的 PNG/JPEG，按版心等比缩放；图片内文字不能作为正文编辑 |
| 内联 `svg` | 静态图表渲染为 PNG 后嵌入，图形与图中标签均为图片 |
| 显式分页 | 使用 `break-before: page` 或 `page-break-before: always`；适用于新章节起页 |

默认页面为 **A4 纵向，四周页边距 20 mm**，可用宽度为 170 mm。首版面向单栏报告，HTML 中的字体、字号和行距会影响 Word 分页；浏览器中的视觉高度不能直接换算成 Word 页数。不要依赖 CSS `@page` 改变文档纸张或页边距。

## CSS 范围与优先级

样式来自内部 `<style>` 和元素的内联 `style`。建议使用简单的标签、类和 ID 选择器，避免依赖交互状态。未声明的样式先继承可继承属性，再采用语义标签和插件默认值；同一属性按 CSS 的重要性、选择器优先级和声明顺序确定有效值，普通内联声明优先于普通样式表声明。样式的优先级不意味着所有 CSS 属性都受支持。

常见字体、字号、粗细、斜体、文字颜色、下划线、段落行距、上下间距、缩进、水平对齐，以及表格宽度、单元格边框、底色、内边距和对齐会映射到 Word。无单位行高按“字号 × 倍数”设置最小行高，大字和图片可以撑高行框。建议字号使用 `pt`，表格宽度使用 `mm` / `pt` 或简单百分比，图片使用明确宽高并保持原始比例。字体使用本机已安装的字体；默认中文字体为 Microsoft YaHei。文档不嵌入字体，接收方缺少字体时，Office 的替代字体可能改变换行和分页。

不支持的装饰样式会显示转换提示。Flex / Grid、多栏视觉布局、浮动和绝对定位按文档顺序展开，无法保留网页的空间关系。不要用这些布局表达重要的阅读顺序，也不要用背景图、伪元素或复杂 CSS 绘制必须保留的内容。转换器不是完整浏览器排版引擎，无法承诺网页像素级还原。

## 阻止导出的内容与资源边界

- 脚本、Canvas 等动态内容会阻止导出。请先将图表转为静态内联 SVG 或 PNG/JPEG，再移除脚本和 Canvas。
- 图片缺失、图片损坏、格式不支持，以及无法可靠转换的表格结构会阻止导出，并提示相关元素或原因。请先修复资源或合并单元格关系。
- 外部样式表、网络图片、远程字体及其他外部资源不会被请求。将需要的 CSS 放入 `<style>`，将图片放入工作区或使用 PNG/JPEG data URI；普通正文超链接不属于资源加载。
- 本地图片路径相对于 HTML 所在目录解析，并通过 Host API 在工作区读取。`../assets/image.png` 等父目录相对路径仅在解析后仍位于工作区内时可用；不能借助绝对路径、目录穿越或符号链接读取工作区外文件。图片路径不支持查询参数或 `#片段`。
- SVG 必须直接内联在 HTML 中，只包含静态内容，不含脚本或外部引用。建议用基本图形和文字绘制图表；不要用 `<img src="chart.svg">` 或 SVG data URI 代替内联 SVG。
- 超出输入、资源、图片像素、结构数量或转换时间限额时，导出失败并显示原因；宿主的读取和产物大小限额也同时适用。

插件仅申请 `workspaceRead` 和 `tempArtifacts` 权限。检查与导出使用独立转换 worker；超时只结束该次转换 worker。生成的 DOCX 通过 Host API 发布为临时产物供下载，不覆盖源 HTML。

## 配置

通过插件设置修改以下值。默认字体 / 字号只作为未指定样式时的回退；显式 HTML 样式仍按层叠规则生效。

| 配置键 | 默认值 | 含义 |
| --- | --- | --- |
| `defaultFont` | `Microsoft YaHei` | 正文默认字体，包含中文东亚字体设置 |
| `defaultFontSizePt` | `11` | 正文默认字号，单位 pt |
| `maxSourceBytes` | `2097152` | 源 HTML 大小，默认 2 MiB；内嵌 data URI 也占用源大小 |
| `maxResourceBytes` | `16777216` | 图片等资源的总字节限额，默认 16 MiB |
| `maxImagePixels` | `16000000` | 单张图片像素数量限额；压缩后文件很小的图片也可能超限 |
| `maxElements` | `10000` | 文档元素数量限额 |
| `maxTableCells` | `10000` | 表格网格数量限额，合并单元格仍占用所覆盖的网格 |
| `conversionTimeoutSeconds` | `45` | 一次操作的总预算，包含解析、资源读取和生成；最高 55 秒 |

## 样例

| 文件 | 内容与检查重点 |
| --- | --- |
| `samples/comprehensive-report.html` | 约三页的中英文综合报告，两个显式分页点；含嵌套列表、富文本、链接、代码、合并表格、本地 PNG/JPEG、data URI 图片和静态 SVG 图表 |
| `samples/long-table.html` | 连续 70 行明细，含表头、列宽、分类合并和汇总；按默认版面设计为约 3–5 页，用于检查跨页表格 |
| `samples/assets/process.png` | 确定性绘制的流程插图 |
| `samples/assets/workbench.jpg` | 确定性绘制的工作台示意图 |

样例数据均为虚构。目标页数用于排版检查，实际页数受转换器、字体和 Word / LibreOffice 版本影响；交付前应检查实际 DOCX，不能仅凭 HTML 预览判断通过。

## 可直接交给 AI 的 HTML 编写要求

```text
请生成用于 Orbit HTML → DOCX 插件的静态 UTF-8 HTML 报告。

1. 输出完整 HTML，包含 <!doctype html>、<meta charset="utf-8"> 和清晰的 title。
   只使用内部 <style> 和内联 style，不引入外部 CSS、字体、脚本或其他网络资源。
2. 按单栏文档的阅读顺序组织内容。用 h1–h6、p、blockquote、ul/ol/li、pre/code
   表达语义；子列表放在父 li 内。不要用空格、空行或布局表格模拟排版。
3. 页面按 A4 纵向、四周 20 mm 页边距、170 mm 版心宽度设计。
   使用 Microsoft YaHei 等本机字体，正文约 11 pt，明确标题字号、行距和段落间距。
   不用 @page、Flex/Grid、float、absolute/fixed、多栏、伪元素表达必要内容。
4. 粗体、斜体、下划线、上下标和链接使用语义标签；链接有可读文字，
   目标仅用 http/https/mailto/tel 或 #锚点，不使用相对文件链接。
   pre 中保留必要缩进，并将长代码行主动折行到版心以内。
5. 数据使用原生 table，设置一致的总宽和列宽，并包含 thead 和 tbody。
   单元格可设置简单边框、底色、内边距和对齐。rowspan/colspan 必须形成完整网格，
   不得重叠、越界或省略必要单元格。可为 tr 设置 break-inside: avoid，避免一行中途断页；
   长表允许自然跨页，不把整张长表设为禁止分页。
6. 图片只使用工作区内相对路径的 PNG/JPEG，或 data:image/png;base64,... /
   data:image/jpeg;base64,...；同时提供真实文件或完整数据，写清 alt 和合理尺寸。
   必须保留的图表使用静态内联 SVG 或 PNG/JPEG，不使用 script、canvas、iframe。
   SVG 给出 width、height 和 viewBox，不含脚本、外部文件、网络引用或动态内容。
7. 需要新章节起页时，在章节标题设置 break-before: page，避免同时插入空白页。
   表格和图片不得超出版心；不要承诺 HTML 浏览器效果与 Word 分页完全一致。
8. 默认限制：HTML 2 MiB、资源总量 16 MiB、图片像素限额 16000000、
   文档元素 10000、表格单元格 10000、转换 45 秒。保持内容和资源精简。
   输出前检查相对路径、编码、表格网格和静态资源完整性，不声称未执行的验证已通过。
```
