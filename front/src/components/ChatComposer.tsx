type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
};

export function ChatComposer({ onSend, disabled }: Props) {
  return (
    <form
      className="flex gap-2 p-2 border-t border-[var(--border)] bg-[var(--surface-strong)]"
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
        className="flex-1 resize-none rounded-lg border border-[var(--border)] p-2 bg-[var(--surface)] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
      />
      <button 
        type="submit" 
        disabled={disabled}
        className="px-4 py-2 bg-[var(--accent)] text-white rounded-lg disabled:opacity-50"
      >
        发送
      </button>
    </form>
  );
}
