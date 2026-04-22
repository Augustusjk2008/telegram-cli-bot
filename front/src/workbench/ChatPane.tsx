import { ChatScreen } from "../screens/ChatScreen";
import type { WebBotClient } from "../services/webBotClient";
import type { ChatWorkbenchStatus } from "./workbenchTypes";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  userAvatarName?: string;
  client: WebBotClient;
  readOnly?: boolean;
  allowTrace?: boolean;
  visible?: boolean;
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
  readOnly = false,
  allowTrace = true,
  visible = true,
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
      readOnly={readOnly}
      allowTrace={allowTrace}
      isVisible={visible}
      embedded
      focused={focused}
      onToggleFocus={onToggleFocus}
      onUnreadResult={onUnreadResult}
      onWorkbenchStatusChange={onWorkbenchStatusChange}
    />
  );
}
