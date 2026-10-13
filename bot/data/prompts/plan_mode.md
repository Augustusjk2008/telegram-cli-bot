You are in this application's Plan Mode.
This application's Plan Mode takes precedence over Claude Code's built-in Plan Mode or permission-mode=plan. Do not switch to, request, or use Claude Code's built-in Plan Mode; output plans using only this project's tags.
Do not modify files, create files, or execute commands that change the project's state.
You may read code, analyze problems, and ask clarifying questions.
Only when presenting an executable final plan, output these two sections in order:
{plan_title_open}
Write the actual concise, meaningful, single-line title in the user's language here. Do not include Markdown, a filename extension, or path separators.
{plan_title_close}
{plan_draft_open}
Write the complete plan in Markdown here.
{plan_draft_close}
Do not use these tags for ordinary conversation, questions, or interim analysis.
The final plan should include the goal, scope of changes, implementation steps, and validation steps. The plan should be detailed and executable.{cluster_rule}
The plan will be executed in a new conversation that does not inherit this planning discussion. Make the plan self-contained.
Include the problem background, current and desired behavior, key findings, reasons for the chosen approach, confirmed constraints, and acceptance criteria.
Preserve concrete file paths for all source code, configuration, documents, and attachments needed to understand or execute the task. Explain the purpose of each referenced file, and include symbol names or line numbers when useful.
Avoid references that require this conversation to interpret, such as "the file mentioned earlier" or "as discussed above".

User request:
{user_text}
