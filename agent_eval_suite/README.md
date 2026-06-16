# Agent Eval Suite

Windows 原生 agent 评测套件。默认 `win-native` 预设使用本地确定性题库，可离线跑通 prepare/score/report；外部官方数据和模型 grader 可后续接入同一答案格式。

说明：
- IFEval：本地实现 verifiable instruction 子集，输出 strict/loose prompt 和 instruction 指标。
- SimpleQA：默认确定性判分；`--simpleqa-grader openai` 需 `OPENAI_API_KEY` 和 grader model。
- EvalPlus：Windows 子进程适配，输出 base/plus pass@1、timeout、runtime_error。
- GAIA-lite：只做 final-answer exact match；GAIA 数据集有 gated 条款，不随仓库分发官方题和答案。
- `private_gold` 位于 workspace 外；这降低误读风险，但 cwd 本身不是安全沙箱。

## 用法

```powershell
cd agent_eval_suite
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

python -m suite prepare --run r001 --preset win-native --samples 50
```

也可在仓库根执行：

```powershell
python -m suite prepare --suite-root agent_eval_suite --run r001 --preset win-native --samples 50
```

把 agent 工作区设为：

```text
agent_eval_suite\runs\r001\workspace
```

把 `PROMPT.md` 内容发给 agent。agent 只需生成：

```text
answers/ifeval.jsonl
answers/simpleqa.jsonl
answers/evalplus.jsonl
answers/gaia.jsonl
```

评分和报告：

```powershell
python -m suite score --run r001
python -m suite report --run r001 --open
```

隐藏答案和隐藏测试写入 `private_gold/<run_id>/`，不会写入 workspace。

## 可选外部数据

默认题库为本地 smoke/win-native。可选接入：

```powershell
python -m suite prepare --run r002 --preset win-native --samples 50 `
  --ifeval-input C:\data\ifeval.jsonl `
  --simpleqa-csv C:\data\simpleqa.csv `
  --evalplus-source humaneval-plus `
  --gaia-jsonl C:\data\gaia-lite.jsonl
```

`--evalplus-source humaneval-plus` 需安装 `evalplus`。IFEval 官方 grader 需本地可导入 `instruction_following_eval`。
