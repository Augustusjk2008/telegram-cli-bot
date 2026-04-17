import { ChatScreen } from "../screens/ChatScreen";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  userAvatarName?: string;
  client: WebBotClient;
};

export function ChatPane({ botAlias, botAvatarName, userAvatarName, client }: Props) {
  return (
    <ChatScreen
      botAlias={botAlias}
      botAvatarName={botAvatarName}
      userAvatarName={userAvatarName}
      client={client}
      isVisible
      embedded
    />
  );
}
