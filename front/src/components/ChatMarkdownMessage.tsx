import { Component, memo, type ReactNode } from "react";
import { ChatPlainTextMessage } from "./ChatPlainTextMessage";
import { MarkdownContent } from "./MarkdownPreview";

type Props = {
  content: string;
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
        <div data-testid="assistant-markdown-fallback">
          <ChatPlainTextMessage
            content={this.props.content}
            className="text-[var(--text)]"
          />
        </div>
      );
    }

    return (
        <div data-testid="assistant-markdown-message" className={`min-w-0 w-full overflow-hidden ${this.props.className || ""}`}>
        <MarkdownContent content={this.props.content} variant="chat" onFileLinkClick={this.props.onFileLinkClick} />
      </div>
    );
  }
}

function ChatMarkdownMessageInner({ content, onFileLinkClick, className }: Props) {
  return <ChatMarkdownBoundary content={content} onFileLinkClick={onFileLinkClick} className={className} />;
}

export const ChatMarkdownMessage = memo(ChatMarkdownMessageInner);
