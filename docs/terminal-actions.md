# 终端快捷命令

终端页支持把项目常用命令配置成按钮。配置文件固定放在工作区：

```text
scripts/terminal-actions.json
```

可从 `scripts/terminal-actions.example.json` 复制后修改。

## 配置格式

```json
{
  "schemaVersion": 1,
  "actions": [
    {
      "id": "test",
      "label": "运行测试",
      "icon": "TestTube2",
      "command": "npm test -- --run",
      "cwd": "front",
      "confirm": false,
      "enabled": true
    }
  ]
}
```

字段：

- `id`: 唯一 ID，支持字母、数字、`.`、`_`、`-`，最长 64 字符。
- `label`: 按钮文字，1-40 字符。
- `icon`: 图标名，不在白名单内会回退到 `Terminal`。
- `command`: 写入终端的单行命令，最长 2000 字符。
- `cwd`: 执行目录，相对工作区解析，不能越界，目录必须存在。
- `confirm`: `true` 时点击前二次确认。
- `enabled`: `false` 时不显示，也不可执行。

## 可视化配置

终端页右上角点击设置按钮，可新增、删除、排序和编辑快捷命令。保存会写回同一个 JSON 文件；如文件被其他进程改过，界面会提示冲突，需刷新后再保存。

## 执行行为

点击按钮后，后端会校验当前配置并把命令写入持久终端：

- 如终端未启动，会按该动作的 `cwd` 新建终端。
- 如终端已启动，会复用现有终端，只发送命令，不切换已运行终端目录。
- `confirm: true` 的动作必须经前端确认后才能执行。

## 权限和安全

- 读取配置需当前 bot 可访问工作区。
- 保存配置需 `write_files` 能力。
- 执行动作需 `terminal.exec` 能力。
- `cwd` 会限制在工作区内，防止从配置跳到工作区外目录。
