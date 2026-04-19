import { ChatScreen } from "../screens/ChatScreen";
import type { WebBotClient } from "../services/webBotClient";
import type { ChatWorkbenchStatus } from "./workbenchTypes";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  userAvatarName?: string;
  client: WebBotClient;
  focused?: boolean;
  onToggleFocus?: () => void;
  onUnreadResult?: (botAlias: string) => void;
  onWorkbenchStatusChange?: (status: ChatWorkbenchStatus) => void;
};

export function ChatPane({
  botAlias,
  botAvatarName,
  userAvatarName,
  client,
  focused = false,
  onToggleFocus,
  onUnreadResult,
  onWorkbenchStatusChange,
}: Props) {
  return (
    <ChatScreen
      botAlias={botAlias}
      botAvatarName={botAvatarName}
      userAvatarName={userAvatarName}
      client={client}
      isVisible
      embedded
      focused={focused}
      onToggleFocus={onToggleFocus}
      onUnreadResult={onUnreadResult}
      onWorkbenchStatusChange={onWorkbenchStatusChange}
    />
  );
}
