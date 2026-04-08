import { useState } from "react";
import { LogOut, RefreshCw, AlertTriangle } from "lucide-react";

export function SettingsScreen({ onLogout }: { onLogout: () => void }) {
  const [showConfirm, setShowConfirm] = useState(false);

  const handleReset = () => {
    setShowConfirm(true);
  };

  const confirmReset = () => {
    alert("模拟重置成功");
    setShowConfirm(false);
  };

  return (
    <main className="flex flex-col h-full bg-[var(--bg)]">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
        <h1 className="text-xl font-bold">设置</h1>
      </header>
      
      <section className="flex-1 overflow-y-auto p-4 space-y-6">
        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] overflow-hidden divide-y divide-[var(--border)]">
          <button 
            onClick={handleReset}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <RefreshCw className="w-5 h-5" />
              重置当前会话
            </span>
          </button>
          <button 
            onClick={onLogout}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)]"
          >
            <span className="flex items-center gap-3">
              <LogOut className="w-5 h-5" />
              退出登录
            </span>
          </button>
        </div>
      </section>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">危险操作</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要重置当前会话吗？此操作不可恢复。</p>
            <div className="flex gap-3 justify-end">
              <button 
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button 
                onClick={confirmReset}
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                确定重置
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
