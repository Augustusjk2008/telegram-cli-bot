import { Fragment } from "react";

/** Tiny inline formatter: `code` in backticks becomes <code>. The Markdown renderer is deliberately not used. */
export function TutorialText({ text }: { text: string }) {
  return (
    <>
      {text.split("`").map((part, index) => (
        index % 2 === 1 ? <code key={index}>{part}</code> : <Fragment key={index}>{part}</Fragment>
      ))}
    </>
  );
}
