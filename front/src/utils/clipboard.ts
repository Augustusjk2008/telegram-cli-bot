/**
 * Copies text that is still being prepared. The clipboard write starts inside the
 * user gesture (browsers reject writes that begin after an awaited request), with
 * the regular copy as the fallback.
 */
export async function copyDeferredText(pendingText: Promise<string>): Promise<boolean> {
  const clipboard = globalThis.navigator?.clipboard;
  if (clipboard?.write && typeof ClipboardItem !== "undefined") {
    try {
      await clipboard.write([
        new ClipboardItem({
          "text/plain": pendingText.then((text) => new Blob([text], { type: "text/plain" })),
        }),
      ]);
      return true;
    } catch {
      // Fall back for browsers that do not accept a pending clipboard item.
    }
  }
  let text = "";
  try {
    text = await pendingText;
  } catch {
    return false;
  }
  return text ? copyText(text) : false;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    const clipboard = globalThis.navigator?.clipboard;
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back for browsers/environments that expose clipboard but reject it.
  }

  if (typeof document === "undefined") {
    return false;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    textarea.remove();
  }
}
