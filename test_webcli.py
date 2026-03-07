"""测试 Web CLI bot 添加"""

import json
from pathlib import Path

# 读取现有配置
config_file = Path("managed_bots.json")
if config_file.exists():
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {"bots": []}

# 添加 webcli bot（需要替换为实际的 token）
webcli_bot = {
    "alias": "webcli",
    "token": "YOUR_BOT_TOKEN_HERE",  # 需要替换
    "cli_type": "claude",
    "cli_path": "claude",
    "working_dir": "C:\\Users\\JiangKai\\telegram_cli_bridge\\refactoring",
    "enabled": True,
    "bot_mode": "webcli"
}

# 检查是否已存在
existing = [b for b in data["bots"] if b.get("alias") == "webcli"]
if existing:
    print("webcli bot 已存在，更新配置...")
    for b in data["bots"]:
        if b.get("alias") == "webcli":
            b.update(webcli_bot)
else:
    print("添加新的 webcli bot...")
    data["bots"].append(webcli_bot)

# 保存配置
with open(config_file, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("配置已保存到 managed_bots.json")
print("\n请手动编辑文件，将 YOUR_BOT_TOKEN_HERE 替换为实际的 bot token")
