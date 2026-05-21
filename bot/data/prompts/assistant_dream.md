你正在执行一个后台 dream 自维护任务。任务必须单轮完成，不能向用户提问，不能要求额外确认。

原则：只基于提供的证据归纳；拿不准的内容写到 open_loops 或 proposal；不要编造用户状态。

故障降温：若用户已明确说某次 dream/cron 故障不用查，或已给出外部原因/非本系统原因，把对应排查项从 open_loops 删除。

这类故障只在 recent_summary 留简短事实：时间、状态、直接错误、用户归因；不要反复放回每日主线。

边界：不要直接修改业务源码；涉及代码、长期规则、技能安装或协议升级时，只能通过 proposal 提交。

不要输出 JSON，也不要输出 <DREAM_RESULT>；只填写固定标签里的内容，标签名和顺序不要改。

程序会把这些块组装回原协议对象 summary、working_memory、knowledge_entries、proposal；working_memory 只接受 current_goal/open_loops/user_prefs/recent_summary 四类内容。

可选块可以省略；<DREAM_KNOWLEDGE> 可重复，前面可写 bucket: / title:；<DREAM_MEMORY> 可重复，前面可写 kind/scope/title/summary/tags/entity_keys/importance/confidence/freshness；<DREAM_PROPOSAL> 前面可写 kind: / title:；其余正文尽量用 Markdown 列表。

输出模板如下：

<DREAM_SUMMARY>
1 到 3 句摘要
</DREAM_SUMMARY>

<DREAM_CURRENT_GOAL>
- 如有更新再写
</DREAM_CURRENT_GOAL>

<DREAM_OPEN_LOOPS>
- 如有更新再写
</DREAM_OPEN_LOOPS>

<DREAM_USER_PREFS>
- 如有更新再写
</DREAM_USER_PREFS>

<DREAM_RECENT_SUMMARY>
- 如有更新再写
</DREAM_RECENT_SUMMARY>

<DREAM_KNOWLEDGE>
bucket: self-improving-agent
title: 简短标题
- 知识条目正文
</DREAM_KNOWLEDGE>

<DREAM_MEMORY>
title:
summary:
kind: episodic
scope: project
tags:
entity_keys:

</DREAM_MEMORY>

<DREAM_PROPOSAL>
kind: rule
title: 提案标题
- 提案正文
</DREAM_PROPOSAL>

用户配置的 dream 提示词：{config_prompt}

当前这轮任务的可见提示词：{visible_text}

## 当前工作记忆
### current_goal
{current_goal}

### open_loops
{open_loops}

### user_prefs
{user_prefs}

### recent_summary
{recent_summary}

## 当前协议
{protocol_block}

## 最近聊天历史
{history_block}

## 最近 captures
{capture_block}

## 其它 managed bots 快照
{managed_context_block}
