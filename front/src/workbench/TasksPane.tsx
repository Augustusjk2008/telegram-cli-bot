import { Play, RefreshCw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { TaskRunResult, WorkspaceTask } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  onProblemsChanged: () => void;
};

export function TasksPane({ botAlias, client, onProblemsChanged }: Props) {
  const [tasks, setTasks] = useState<WorkspaceTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [runningTaskId, setRunningTaskId] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [result, setResult] = useState<TaskRunResult | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  async function loadTasks() {
    setLoading(true);
    try {
      const nextTasks = await client.listTasks(botAlias);
      setTasks(nextTasks);
      setError("");
    } catch (caught) {
      setTasks([]);
      setError(caught instanceof Error ? caught.message : "读取任务失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTasks();
    return () => {
      controllerRef.current?.abort();
    };
  }, [botAlias, client]);

  async function runTask(task: WorkspaceTask) {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setRunningTaskId(task.id);
    setLogs([]);
    setResult(null);
    setError("");

    try {
      const nextResult = await client.runTaskStream(
        botAlias,
        task.id,
        (event) => {
          if (event.type === "log" && event.text) {
            setLogs((current) => [...current, event.text]);
          }
          if (event.type === "done") {
            setResult(event.result);
          }
        },
        { signal: controller.signal },
      );
      setResult(nextResult);
      onProblemsChanged();
    } catch (caught) {
      if (controller.signal.aborted) {
        setLogs((current) => [...current, "任务已取消"]);
      } else {
        setError(caught instanceof Error ? caught.message : "任务执行失败");
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
      setRunningTaskId("");
    }
  }

  function cancelTask() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setRunningTaskId("");
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-3">
        <h2 className="text-sm font-semibold text-[var(--text)]">任务</h2>
        <button
          type="button"
          aria-label="刷新任务"
          onClick={() => void loadTasks()}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? <div className="px-3 py-3 text-sm text-[var(--muted)]">加载中...</div> : null}
        {error ? <div className="px-3 py-3 text-sm text-red-600">{error}</div> : null}
        {!loading && !error && tasks.length === 0 ? <div className="px-3 py-3 text-sm text-[var(--muted)]">无任务</div> : null}
        {tasks.map((task) => (
          <div key={task.id} className="border-b border-[var(--border)] px-3 py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-medium text-[var(--text)]">{task.label}</h3>
                <p className="truncate font-mono text-xs text-[var(--muted)]">{task.command}</p>
              </div>
              {runningTaskId === task.id ? (
                <button
                  type="button"
                  aria-label="取消任务"
                  onClick={cancelTask}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
                >
                  <Square className="h-4 w-4" />
                </button>
              ) : (
                <button
                  type="button"
                  aria-label={`运行 ${task.id}`}
                  disabled={Boolean(runningTaskId)}
                  onClick={() => void runTask(task)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <Play className="h-4 w-4" />
                </button>
              )}
            </div>
            {task.detail ? <p className="mt-2 line-clamp-2 text-xs text-[var(--muted)]">{task.detail}</p> : null}
          </div>
        ))}
      </div>
      <div className="max-h-56 min-h-24 overflow-y-auto border-t border-[var(--border)] bg-[var(--surface-strong)] p-3">
        {result ? (
          <div className={result.success ? "text-xs text-emerald-600" : "text-xs text-red-600"}>
            {result.success ? "任务通过" : `任务失败，退出码 ${result.returnCode}`}
          </div>
        ) : null}
        <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-[var(--text)]">
          {logs.length ? logs.join("\n") : "等待任务输出"}
        </pre>
      </div>
    </section>
  );
}
