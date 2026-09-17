import { Component, memo, type ReactNode } from "react";
import { ChatPlainTextMessage } from "./ChatPlainTextMessage";
import { MarkdownContent } from "./MarkdownPreview";

type Props = {
  content: string;
  role?: "assistant" | "user";
  onFileLinkClick?: (href: string) => void;
  className?: string;
};

type State = {
  hasError: boolean;
};

class ChatMarkdownBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: Props) {
    if (this.state.hasError && prevProps.content !== this.props.content) {
      this.setState({ hasError: false });
    }
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div data-testid={`${this.props.role || "assistant"}-markdown-fallback`} className={this.props.className}>
          <ChatPlainTextMessage
            content={this.props.content}
            className="text-[var(--chat-markdown-text,var(--text))]"
          />
        </div>
      );
    }

    return (
      <div data-testid={`${this.props.role || "assistant"}-markdown-message`} className={`min-w-0 w-full overflow-hidden ${this.props.className || ""}`}>
        <MarkdownContent content={this.props.content} variant="chat" onFileLinkClick={this.props.onFileLinkClick} />
      </div>
    );
  }
}

function ChatMarkdownMessageInner(props: Props) {
  return <ChatMarkdownBoundary {...props} />;
}

export const ChatMarkdownMessage = memo(ChatMarkdownMessageInner);
