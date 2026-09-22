# PPTX Preview

将 `.pptx` 幻灯片转换为 PDF，在工作台中按静态页面预览，支持翻页、缩放和文字选择。包含隐藏幻灯片，不播放动画、切换效果、音视频，也不显示演讲者备注。

## 安装与配置

1. 在运行 Orbit 后端的机器上安装 LibreOffice（含 Impress），并安装演示文稿使用的字体。
2. 在插件管理页安装或重新安装 **PPTX Preview**，启用后打开工作区内的 `.pptx` 文件。
3. 插件自动查找 PATH、Windows 默认安装目录和 macOS 应用目录。未找到时，在插件设置的 **LibreOffice 路径** 中填写可执行文件完整路径，例如 `C:\Program Files\LibreOffice\program\soffice.com`。

默认预览前 80 页，可通过 **最多幻灯片** 调整到 1–300 页。超出页数时会显示提示。单次转换最多 40 秒，生成的 PDF 最多 32 MiB；超限时可减少页数或压缩图片。

转换在本机临时目录中进行，使用独立的 LibreOffice 配置并禁用宏，不修改源文件或占用已打开的 Office 会话。临时转换文件在完成或失败后清理，预览通过现有的插件产物接口读取，无需公开上传文件。

版式由 LibreOffice 渲染；缺失字体、SmartArt 或 PowerPoint 专有特效可能与 PowerPoint 中的显示有差异。插件使用 LibreOffice 的 [命令行参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html) 与 [PDF 导出参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html)。
