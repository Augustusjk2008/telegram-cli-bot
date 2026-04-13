import { Fragment } from "react";

type Props = {
  content: string;
  className?: string;
};

function joinClassNames(...parts: Array<string | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function splitParagraphs(content: string) {
  return content
    .replace(/\r\n/g, "\n")
    .split(/\n\s*\n+/)
    .filter((paragraph) => paragraph.length > 0);
}

export function ChatPlainTextMessage({ content, className }: Props) {
  const paragraphs = splitParagraphs(content);

  return (
    <div className={joinClassNames("chat-body-content chat-plain-text-content", className)}>
      {paragraphs.map((paragraph, paragraphIndex) => (
        <p key={`${paragraphIndex}-${paragraph.slice(0, 24)}`} className="m-0 whitespace-pre-wrap break-all [overflow-wrap:anywhere]">
          {paragraph.split("\n").map((line, lineIndex) => (
            <Fragment key={`${paragraphIndex}-${lineIndex}`}>
              {lineIndex > 0 ? <br /> : null}
              {line}
            </Fragment>
          ))}
        </p>
      ))}
    </div>
  );
}
