import { lazy, Suspense } from "react";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";
import type { WebBotClient } from "../services/webBotClient";

const TerminalScreen = lazy(() =>
  import("../screens/TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

type Props = {
  authToken: string;
  botAlias: string;
  client: WebBotClient;
  preferredWorkingDir: string;
  themeName?: UiThemeName;
};

export function TerminalPane({
  authToken,
  botAlias,
  client,
  preferredWorkingDir,
  themeName = DEFAULT_UI_THEME,
}: Props) {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">加载终端...</div>}>
      <TerminalScreen
        authToken={authToken}
        botAlias={botAlias}
        client={client}
        isVisible
        preferredWorkingDir={preferredWorkingDir}
        themeName={themeName}
        embedded
      />
    </Suspense>
  );
}
