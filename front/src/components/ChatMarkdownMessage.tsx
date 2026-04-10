import { Component, type ReactNode } from "react";
import { MarkdownContent } from "./MarkdownPreview";

type Props = {
  content: string;
  onFileLinkClick?: (href: string) => void;
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
        <pre
          data-testid="assistant-markdown-fallback"
          className="whitespace-pre-wrap break-all text-[15px] leading-7 [overflow-wrap:anywhere]"
        >
          {this.props.content}
        </pre>
      );
    }

    return (
      <div data-testid="assistant-markdown-message" className="min-w-0 w-full">
        <MarkdownContent content={this.props.content} variant="chat" onFileLinkClick={this.props.onFileLinkClick} />
      </div>
    );
  }
}

export function ChatMarkdownMessage({ content, onFileLinkClick }: Props) {
  return <ChatMarkdownBoundary content={content} onFileLinkClick={onFileLinkClick} />;
}
