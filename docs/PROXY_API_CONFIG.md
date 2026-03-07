# 代理商 API 配置说明

## 概述

本项目支持使用第三方代理商的 Claude API，而不仅限于 Anthropic 官方 API。这对于国内用户或需要使用中转服务的场景非常有用。

## 配置方法

### 1. 在 `.env` 文件中添加以下配置

```bash
# Claude API Key（从代理商获取）
ANTHROPIC_API_KEY=your_proxy_api_key_here

# Claude 模型名称（根据代理商支持的模型填写）
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# 代理商 API Base URL
ANTHROPIC_BASE_URL=https://api.your-proxy.com/v1
```

### 2. 配置说明

- **ANTHROPIC_API_KEY**: 从代理商处获取的 API Key（不是 Anthropic 官方的 Key）
- **ANTHROPIC_MODEL**: 模型名称，需要确认代理商支持该模型
- **ANTHROPIC_BASE_URL**: 代理商提供的 API 地址
  - 如果留空，则使用 Anthropic 官方 API
  - 通常格式为 `https://api.example.com/v1`

### 3. 常见代理商示例

```bash
# 示例 1: 某代理商
ANTHROPIC_BASE_URL=https://api.example.com/v1

# 示例 2: 另一个代理商
ANTHROPIC_BASE_URL=https://proxy.example.com/anthropic/v1
```

## 工作原理

代码会检查 `ANTHROPIC_BASE_URL` 环境变量：

```python
# bot/assistant/llm.py
client_kwargs = {"api_key": ANTHROPIC_API_KEY}

if ANTHROPIC_BASE_URL:
    client_kwargs["base_url"] = ANTHROPIC_BASE_URL
    logger.info(f"使用自定义 API 地址: {ANTHROPIC_BASE_URL}")

client = anthropic.Anthropic(**client_kwargs)
```

当设置了 `ANTHROPIC_BASE_URL` 时，所有 API 请求都会发送到该地址，而不是 Anthropic 官方服务器。

## 验证配置

运行以下命令验证配置是否正确加载：

```bash
python -c "from bot.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_BASE_URL; print(f'API_KEY: {\"已设置\" if ANTHROPIC_API_KEY else \"未设置\"}'); print(f'MODEL: {ANTHROPIC_MODEL}'); print(f'BASE_URL: {ANTHROPIC_BASE_URL if ANTHROPIC_BASE_URL else \"使用官方API\"}')"
```

预期输出：
```
API_KEY: 已设置
MODEL: claude-3-5-sonnet-20241022
BASE_URL: https://api.your-proxy.com/v1
```

## 故障排查

### 问题：连接失败或超时

**可能原因**：
1. `ANTHROPIC_BASE_URL` 格式不正确
2. 代理商服务不可用
3. API Key 不匹配

**解决方法**：
1. 确认 URL 格式正确（包含 `https://` 前缀）
2. 在浏览器或 curl 中测试代理商 API 是否可访问
3. 确认 API Key 是从该代理商获取的

### 问题：模型不支持

**可能原因**：
代理商不支持指定的模型

**解决方法**：
查看代理商文档，确认支持的模型列表，修改 `ANTHROPIC_MODEL` 配置

### 问题：日志中没有 "使用自定义 API 地址" 提示

**可能原因**：
`ANTHROPIC_BASE_URL` 未设置或为空

**解决方法**：
检查 `.env` 文件中是否正确设置了该变量，确保没有多余的空格

## 与官方 API 的切换

如果需要切换回 Anthropic 官方 API，只需：

1. 将 `ANTHROPIC_BASE_URL` 留空或注释掉
2. 使用 Anthropic 官方的 API Key

```bash
# 使用官方 API
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
# ANTHROPIC_BASE_URL=  # 留空或注释
```

## 安全建议

1. 不要将 `.env` 文件提交到版本控制系统
2. 使用 `.env.example` 作为配置模板
3. 定期更换 API Key
4. 选择可信赖的代理商服务
