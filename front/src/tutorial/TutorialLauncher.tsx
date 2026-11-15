import { lazy, Suspense, useCallback, useRef, useState } from "react";
import { AppLogo } from "../components/AppLogo";
import { ChatConfirmDialog } from "../components/ChatConfirmDialog";
import { readTutorialProgress, updateTutorialProgress } from "./tutorialProgress";

// The guide (code, content and styles) stays out of the entry chunk; the prompt warms it up.
const loadTutorialOverlay = () => import("./TutorialOverlay");
const TutorialOverlay = lazy(loadTutorialOverlay);

type LauncherStage = "idle" | "prompt" | "open";

/** Workbench header logo: opens the usage tutorial after a yes/no prompt. */
export function TutorialLauncher() {
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [stage, setStage] = useState<LauncherStage>("idle");
  const [seen, setSeen] = useState(() => readTutorialProgress().seen);
  const [loadFailed, setLoadFailed] = useState(false);

  const openPrompt = () => {
    void loadTutorialOverlay().catch(() => undefined);
    if (!seen) {
      updateTutorialProgress({ seen: true });
      setSeen(true);
    }
    setLoadFailed(false);
    setStage("prompt");
  };

  const confirmPrompt = () => {
    // Mount the lazy component only after its chunk has loaded, so a failed download can be retried.
    loadTutorialOverlay().then(
      () => setStage((current) => (current === "prompt" ? "open" : current)),
      () => setLoadFailed(true),
    );
  };

  const handleClosed = useCallback(() => setStage("idle"), []);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label="使用教程"
        title="使用教程"
        aria-haspopup="dialog"
        data-tutorial-hint={seen ? undefined : "true"}
        onClick={openPrompt}
        className="workbench-topbar-logo flex h-7 w-7 shrink-0 items-center justify-center"
      >
        <AppLogo size={24} decorative />
      </button>
      {stage === "prompt" ? (
        <ChatConfirmDialog
          label="使用教程"
          title={loadFailed ? "教程加载失败" : "查看使用教程？"}
          description={loadFailed
            ? "教程资源没有加载成功，请检查网络或刷新页面后重试。"
            : "用截图和简短说明介绍对话、工作台、文件、Git、集群等功能，可随时按 Esc 退出。"}
          confirmLabel={loadFailed ? "重试" : "查看教程"}
          cancelLabel="暂不"
          onConfirm={confirmPrompt}
          onCancel={() => setStage("idle")}
        />
      ) : null}
      {stage === "open" ? (
        <Suspense fallback={null}>
          <TutorialOverlay originRef={buttonRef} onClosed={handleClosed} />
        </Suspense>
      ) : null}
    </>
  );
}
