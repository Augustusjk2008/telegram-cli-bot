# Agent Eval Suite

Windows 原生 agent 评测套件。默认 `win-native` 用本地确定性题库离线跑通 prepare/score/report；`win-native-hard` 追加真实 workspace 文件操作题。

## 目录结构

```text
agent_eval_suite/
  README.md
  requirements.txt
  suite/
    cli.py              # python -m suite 入口
    paths.py            # run/workspace/private_gold 路径和 benchmark registry
    data.py             # smoke/win-native/win-native-hard 题库生成
    prepare.py          # 生成 workspace、tasks、private_gold、PROMPT.md
    validation.py       # answers JSONL schema 校验
    scoring.py          # 按 manifest.enabled_benchmarks 调 grader
    report.py           # 生成 summary.csv/report.html
    graders/
      ifeval.py
      simpleqa.py
      evalplus.py
      gaia.py
      workspace.py      # workspace_ops 文件态/命令评分器
  tests/
    test_gaia_grader.py
    test_workspace_grader.py
  runs/<run_id>/        # 生成的 agent workspace 和报告，git 忽略
  private_gold/<run_id>/# 隐藏答案/checks，git 忽略
```

仓库根有 `suite.py` shim，所以可从根目录运行 `python -m suite --suite-root agent_eval_suite ...`。进入 `agent_eval_suite/` 后可省略 `--suite-root`。

## Benchmark

- `ifeval`：本地 verifiable instruction 子集，输出 strict/loose prompt 和 instruction 指标。
- `simpleqa`：默认确定性判分；`--simpleqa-grader openai` 需 `OPENAI_API_KEY` 和 grader model。
- `evalplus`：Windows subprocess adapter，输出 base/plus pass@1、timeout、runtime_error。
- `gaia`：GAIA-lite final-answer exact match；官方 gated 数据不随仓库分发。
- `workspace_ops`：`win-native-hard` 专用，要求 agent 进入 `cases/<id>` 改文件/补报告/修 manifest，再按隐藏 checks 评分。

## Preset

| Preset | Benchmark | 用途 |
| --- | --- | --- |
| `smoke` | `ifeval/simpleqa/evalplus/gaia` | 流程验收、快速回归 |
| `win-native` | `ifeval/simpleqa/evalplus/gaia` | 默认本地评测 |
| `win-native-hard` | 旧 4 项 + `workspace_ops` | 测真实 agent 文件操作能力 |

## 快速使用

从仓库根运行：

```powershell
python -m suite prepare --suite-root agent_eval_suite --run run001 --preset win-native --samples 50
```

或进入套件目录：

```powershell
cd agent_eval_suite
python -m suite prepare --run run001 --preset win-native --samples 50
```

把 agent 工作目录设为：

```text
agent_eval_suite\runs\run001\workspace
```

把 `PROMPT.md` 内容发给 agent。agent 只需读 `tasks/`，写 `answers/`。

旧 4 项答案文件：

```text
answers/ifeval.jsonl
answers/simpleqa.jsonl
answers/evalplus.jsonl
answers/gaia.jsonl
```

评分和报告：

```powershell
python -m suite score --suite-root agent_eval_suite --run run001
python -m suite report --suite-root agent_eval_suite --run run001
```

## Hard preset

```powershell
python -m suite prepare --suite-root agent_eval_suite --run run002 --preset win-native-hard --samples 20
python -m suite score --suite-root agent_eval_suite --run run002 --evalplus-timeout 1.0
python -m suite report --suite-root agent_eval_suite --run run002
```

`win-native-hard` 会额外生成：

```text
runs/run002/workspace/tasks/workspace_ops.jsonl
runs/run002/workspace/cases/<id>/
runs/run002/workspace/answers/workspace_ops.jsonl   # agent 需要写
private_gold/run002/workspace_ops.jsonl             # 隐藏 checks，不进 workspace
```

`workspace_ops` answer schema：

```jsonl
{"id":"workspace_0001","status":"done","summary":"fixed add_tags"}
```

隐藏 checks 支持：

- `file_exists`
- `text_contains`
- `text_equals`
- `json_field_equals`
- `glob_count`
- `command_exit_zero`

`command_exit_zero` 使用 `subprocess.run(argv, cwd=case_dir, timeout=...)`，不走 shell。

## 产物说明

```text
runs/<run_id>/run.json
runs/<run_id>/manifest.json
runs/<run_id>/workspace/PROMPT.md
runs/<run_id>/workspace/tasks/*.jsonl
runs/<run_id>/workspace/answers/*.jsonl
runs/<run_id>/workspace/cases/...        # hard preset 可见资料/待修改项目
runs/<run_id>/report/results.json
runs/<run_id>/report/summary.csv
runs/<run_id>/report/report.html
private_gold/<run_id>/*.jsonl
```

`private_gold` 位于 workspace 外，不写入 agent 工作区。cwd 不是安全沙箱，只是降低误读风险。

## 可选外部数据

```powershell
python -m suite prepare --suite-root agent_eval_suite --run r002 --preset win-native --samples 50 `
  --ifeval-input C:\data\ifeval.jsonl `
  --simpleqa-csv C:\data\simpleqa.csv `
  --evalplus-source humaneval-plus `
  --gaia-jsonl C:\data\gaia-lite.jsonl
```

`--evalplus-source humaneval-plus` 需安装 `evalplus`。IFEval 官方 grader 需本地可导入 `instruction_following_eval`。

## 测试

```powershell
python -m pytest agent_eval_suite/tests/test_workspace_grader.py -q
python -m pytest tests/test_agent_eval_suite.py -q
```

完整 dry run：

```powershell
python -m suite prepare --suite-root agent_eval_suite --run dry-hard --preset win-native-hard --samples 10 --overwrite
python -m suite score --suite-root agent_eval_suite --run dry-hard --evalplus-timeout 1.0
python -m suite report --suite-root agent_eval_suite --run dry-hard
```
