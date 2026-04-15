type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
  compact?: boolean;
};

export function ChatComposer({ onSend, disabled, compact = false }: Props) {
  return (
    <form
      className={compact
        ? "flex gap-2 p-1.5 border-t border-[var(--border)] bg-[var(--surface-strong)]"
        : "flex gap-2 p-2 border-t border-[var(--border)] bg-[var(--surface-strong)]"}
      onSubmit={(event) => {
        event.preventDefault();
        const formData = new FormData(event.currentTarget);
        const text = String(formData.get("message") || "").trim();
        if (!text) return;
        onSend(text);
        event.currentTarget.reset();
      }}
    >
      <textarea 
        name="message" 
        placeholder="输入消息" 
        rows={1} 
        disabled={disabled}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || !event.shiftKey || event.nativeEvent.isComposing) {
            return;
          }
          event.preventDefault();
          const form = event.currentTarget.form;
          if (!form) {
            return;
          }
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
            return;
          }
          form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        }}
        className={compact
          ? "flex-1 resize-none rounded-lg border border-[var(--border)] p-2 bg-[var(--surface)] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
          : "flex-1 resize-none rounded-lg border border-[var(--border)] p-2 bg-[var(--surface)] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"}
      />
      <button 
        type="submit" 
        disabled={disabled}
        className={compact
          ? "px-3.5 py-2 bg-[var(--accent)] text-white rounded-lg disabled:opacity-50"
          : "px-4 py-2 bg-[var(--accent)] text-white rounded-lg disabled:opacity-50"}
      >
        发送
      </button>
    </form>
  );
}
