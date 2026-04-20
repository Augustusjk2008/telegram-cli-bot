type EditorExtension = unknown;

export async function loadFileEditorExtensions(path: string): Promise<EditorExtension[]> {
  const normalizedPath = path.toLowerCase();

  if (/\.(md|markdown)$/.test(normalizedPath)) {
    const { markdown } = await import("@codemirror/lang-markdown");
    return [markdown()];
  }

  if (/\.(js|jsx|mjs|cjs|ts|tsx)$/.test(normalizedPath)) {
    const { javascript } = await import("@codemirror/lang-javascript");
    return [javascript({ jsx: /(\.jsx|\.tsx)$/.test(normalizedPath), typescript: /(\.ts|\.tsx)$/.test(normalizedPath) })];
  }

  if (/\.json$/.test(normalizedPath)) {
    const { json } = await import("@codemirror/lang-json");
    return [json()];
  }

  if (/\.py$/.test(normalizedPath)) {
    const { python } = await import("@codemirror/lang-python");
    return [python()];
  }

  if (/\.(c|cc|cp|cpp|cxx|h|hh|hpp|hxx)$/.test(normalizedPath)) {
    const { cpp } = await import("@codemirror/lang-cpp");
    return [cpp()];
  }

  if (/\.(html|htm)$/.test(normalizedPath)) {
    const { html } = await import("@codemirror/lang-html");
    return [html()];
  }

  if (/\.css$/.test(normalizedPath)) {
    const { css } = await import("@codemirror/lang-css");
    return [css()];
  }

  return [];
}
