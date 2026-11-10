import { FileCode2, Files, MessageSquare, SquareTerminal, type LucideIcon } from "lucide-react";
import type { WorkbenchPaneId } from "./workbenchLayout";

/** Content icons for the four desktop panes; they name what a pane holds, not where it sits. */
export const WORKBENCH_PANE_ICONS: Readonly<Record<WorkbenchPaneId, LucideIcon>> = {
  sidebar: Files,
  editor: FileCode2,
  terminal: SquareTerminal,
  chat: MessageSquare,
};
