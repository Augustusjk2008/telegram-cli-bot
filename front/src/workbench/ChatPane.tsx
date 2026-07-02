import { ChatScreen } from "../screens/ChatScreen";
import type { WebBotClient } from "../services/webBotClient";
import type { ChatWorkbenchStatus } from "./workbenchTypes";

type Props = {
  botAlias: string;
  client: WebBotClient;
  readOnly?: boolean;
  readOnlyReason?: string;
  disabledReason?: string;
  allowTrace?: boolean;
  visible?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onUnreadResult?: (botAlias: string) => void;
  onWorkbenchStatusChange?: (status: ChatWorkbenchStatus) => void;
  onRequestDesktopPreview?: (path: string) => void;
};

export function ChatPane({
  botAlias,
  client,
  readOnly = false,
  readOnlyReason,
  disabledReason,
  allowTrace = true,
  visible = true,
  focused = false,
  onToggleFocus,
  onUnreadResult,
  onWorkbenchStatusChange,
  onRequestDesktopPreview,
}: Props) {
  return (
    <ChatScreen
      botAlias={botAlias}
      client={client}
      readOnly={readOnly}
      readOnlyReason={readOnlyReason}
      disabledReason={disabledReason}
      allowTrace={allowTrace}
      isVisible={visible}
      embedded
      focused={focused}
      onToggleFocus={onToggleFocus}
      onUnreadResult={onUnreadResult}
      onWorkbenchStatusChange={onWorkbenchStatusChange}
      onRequestDesktopPreview={onRequestDesktopPreview}
    />
  );
}
