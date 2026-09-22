# PPTX Preview

无需安装 LibreOffice 或 Microsoft Office 即可打开 `.pptx`，使用内置基础预览展示文本、图片、背景和表格。包含隐藏幻灯片，不播放动画、切换效果、音视频，也不显示演讲者备注。不支持旧版二进制 `.ppt`。

## 安装与配置

在插件管理页安装或重新安装 **PPTX Preview**，启用后打开工作区内的 `.pptx` 文件。**LibreOffice 路径** 可以留空：找不到 LibreOffice 时自动使用内置预览，不报缺少软件错误。

默认预览前 80 页，可通过 **最多幻灯片** 调整到 1–300 页。内置预览每页最多展示 240 个元素；复杂图形、图表、SmartArt、组合对象和继承版式可能不完整，预览界面会提示这一限制。

## 可选：更准确的版式

如果后端机器已安装 LibreOffice（含 Impress），插件会自动使用它转换为 PDF，支持翻页、缩放和文字选择。也可在插件设置中填写完整路径，例如 `C:\Program Files\LibreOffice\program\soffice.com`。自动查找范围包括 PATH、Windows 默认安装目录和 macOS 应用目录。手动填写无效路径时，请修正或清空以恢复自动选择。

LibreOffice 单次转换最多 40 秒，生成的 PDF 最多 32 MiB；超限时可减少页数或压缩图片。

转换在本机临时目录中进行，使用独立的 LibreOffice 配置并禁用宏，不修改源文件或占用已打开的 Office 会话。临时转换文件在完成或失败后清理，预览通过现有的插件产物接口读取，无需公开上传文件。

版式由 LibreOffice 渲染；缺失字体、SmartArt 或 PowerPoint 专有特效可能与 PowerPoint 中的显示有差异。插件使用 LibreOffice 的 [命令行参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html) 与 [PDF 导出参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html)。
