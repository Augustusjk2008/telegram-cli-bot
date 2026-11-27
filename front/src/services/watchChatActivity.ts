import type { WebBotClient } from "./webBotClient";

/** Refresh visible activity lists on turn boundaries, with a fallback for missed socket hints. */
export function watchChatActivity(
  client: WebBotClient,
  refresh: (initial: boolean) => Promise<unknown>,
  botAlias?: string,
) {
  const alias = botAlias?.trim().toLowerCase();
  let stopped = false;
  let running = false;
  let pending = false;
  let timer: number | undefined;

  function schedule() {
    if (stopped || document.visibilityState === "hidden") return;
    if (running) {
      pending = true;
    } else if (timer === undefined) {
      timer = window.setTimeout(() => run(false), 150);
    }
  }

  async function run(initial: boolean) {
    timer = undefined;
    if (stopped || (!initial && document.visibilityState === "hidden")) return;
    running = true;
    try {
      await refresh(initial);
    } finally {
      running = false;
      if (pending) {
        pending = false;
        schedule();
      }
    }
  }

  void run(true);
  const unsubscribe = client.subscribeChatSync?.((event) => {
    if (event.type === "status") {
      if (event.active) schedule();
    } else if ((!alias || event.botAlias.trim().toLowerCase() === alias) && (
      event.reason === "turn_started" || event.reason === "turn_finished"
      || (!alias && event.reason === "cluster")
    )) {
      schedule();
    }
  });
  const poll = window.setInterval(schedule, 15_000);
  window.addEventListener("focus", schedule);
  document.addEventListener("visibilitychange", schedule);
  return () => {
    stopped = true;
    unsubscribe?.();
    window.clearTimeout(timer);
    window.clearInterval(poll);
    window.removeEventListener("focus", schedule);
    document.removeEventListener("visibilitychange", schedule);
  };
}
