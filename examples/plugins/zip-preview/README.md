# Archive Preview

这个插件保留 `zip-preview` 的插件 ID，支持在文件面板中预览并解压：

- ZIP
- TAR、TAR.GZ、TGZ、TAR.BZ2、TBZ、TBZ2、TAR.XZ、TXZ
- 单文件 GZ、BZ2、XZ
- RAR、7z

点击视图工具栏中的「解压到所在文件夹」即可写回压缩包所在目录。解压内容受条目数和总大小限制，路径穿越、符号链接和设备文件会被拒绝；「覆盖同名文件」可以在插件设置中调整。

RAR 和 7z 需要宿主机能找到 `7z`、`7zz` 或 `7za`。RAR 也可以使用已安装并配置好解压后端的 Python `rarfile`。缺少后端时仍会识别插件，但打开文件会显示安装提示。
