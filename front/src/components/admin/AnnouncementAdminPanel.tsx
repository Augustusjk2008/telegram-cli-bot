import { useMemo, type Dispatch, type SetStateAction } from "react";
import { Eye, History, Inbox, Megaphone, Plus, RotateCcw, Send, Trash2, X } from "lucide-react";
import {
  ANNOUNCEMENT_CATEGORIES,
  ANNOUNCEMENT_CATEGORY_LABELS,
  ANNOUNCEMENT_SEVERITIES,
  ANNOUNCEMENT_SEVERITY_LABELS,
  AnnouncementTimeline,
  formatAnnouncementTime,
  renderSafeInlineHtml,
} from "../AnnouncementContent";
import type { AnnouncementItem, CreateAnnouncementInput } from "../../services/types";
import "./AnnouncementAdminPanel.css";

/** Item lines stay raw text while editing so Enter and trailing spaces survive each keystroke. */
export type AnnouncementSectionDraft = { key: number; label: string; itemsText: string };
export type AnnouncementDraft = Omit<CreateAnnouncementInput, "sections"> & { sections: AnnouncementSectionDraft[] };

let sectionKeySeed = 0;

function createSectionDraft(label = ""): AnnouncementSectionDraft {
  sectionKeySeed += 1;
  return { key: sectionKeySeed, label, itemsText: "" };
}

function sectionItems(section: AnnouncementSectionDraft) {
  return section.itemsText.split("\n").map((item) => item.trim()).filter(Boolean);
}

/** A fresh draft; publisher, category and severity carry over so consecutive posts keep their framing. */
export function createAnnouncementDraft(
  carry?: Pick<AnnouncementDraft, "publisher" | "category" | "severity">,
): AnnouncementDraft {
  return {
    publisher: carry?.publisher ?? "CLI Bridge",
    title: "",
    category: carry?.category ?? "feature",
    severity: carry?.severity ?? "info",
    summary: "",
    sections: [createSectionDraft("新增"), createSectionDraft("影响"), createSectionDraft("操作")],
  };
}

/** Matches the backend, which drops sections lacking either a label or an item. */
export function announcementDraftToInput(draft: AnnouncementDraft): CreateAnnouncementInput {
  return {
    publisher: draft.publisher.trim(),
    title: draft.title.trim(),
    category: draft.category,
    severity: draft.severity,
    summary: draft.summary.trim(),
    sections: draft.sections
      .map((section) => ({ label: section.label.trim(), items: sectionItems(section) }))
      .filter((section) => section.label && section.items.length > 0),
  };
}

function plainText(value: string) {
  return value.replace(/<[^>]*>/g, "").trim();
}

type Props = {
  items: AnnouncementItem[];
  draft: AnnouncementDraft;
  onDraftChange: Dispatch<SetStateAction<AnnouncementDraft>>;
  saving: boolean;
  deletingId: string;
  onPublish: () => void;
  onDelete: (id: string) => void;
};

export function AnnouncementAdminPanel({ items, draft, onDraftChange, saving, deletingId, onPublish, onDelete }: Props) {
  const input = useMemo(() => announcementDraftToInput(draft), [draft]);
  const missing = [
    !input.title && "标题",
    !input.publisher && "发布者",
    !input.summary && "摘要",
  ].filter(Boolean);
  const canPublish = missing.length === 0;

  const previewItem = useMemo<AnnouncementItem>(() => ({
    ...input,
    id: "announcement-preview",
    publishedAt: new Date().toISOString(),
    publisher: input.publisher || "发布者",
    title: input.title || "公告标题",
    summary: input.summary || "摘要会显示在标题下方",
  }), [input]);

  const setField = <K extends keyof AnnouncementDraft>(key: K, value: AnnouncementDraft[K]) => {
    onDraftChange((prev) => ({ ...prev, [key]: value }));
  };

  const updateSection = (key: number, patch: Partial<Omit<AnnouncementSectionDraft, "key">>) => {
    onDraftChange((prev) => ({
      ...prev,
      sections: prev.sections.map((section) => (section.key === key ? { ...section, ...patch } : section)),
    }));
  };

  const removeSection = (key: number) => {
    onDraftChange((prev) => ({ ...prev, sections: prev.sections.filter((section) => section.key !== key) }));
  };

  const addSection = () => {
    onDraftChange((prev) => ({ ...prev, sections: [...prev.sections, createSectionDraft()] }));
  };

  const resetDraft = () => {
    onDraftChange((prev) => createAnnouncementDraft(prev));
  };

  return (
    <div className="admin-stack">
      <section aria-labelledby="announce-composer-title" className="admin-island orbit-island orbit-island--reading announce-composer">
        <header className="announce-head">
          <span className="announce-head-icon" aria-hidden="true"><Megaphone className="h-4 w-4" /></span>
          <div className="announce-head-copy">
            <h2 id="announce-composer-title">撰写公告</h2>
            <p>发布后，所有用户下次打开控制台时会弹出提醒</p>
          </div>
        </header>

        <div className="announce-composer-grid">
          <div className="announce-form">
            <div className="announce-fields announce-fields--lead">
              <label className="announce-field">
                <span className="announce-field-label">标题<em aria-hidden="true">*</em></span>
                <input
                  aria-label="公告标题"
                  value={draft.title}
                  placeholder="例如：v2.4 发布，集群编排升级"
                  onChange={(event) => setField("title", event.target.value)}
                  className="w-full border px-3 py-2 text-sm"
                />
              </label>
              <label className="announce-field">
                <span className="announce-field-label">发布者<em aria-hidden="true">*</em></span>
                <input
                  aria-label="公告发布者"
                  value={draft.publisher}
                  placeholder="公告署名"
                  onChange={(event) => setField("publisher", event.target.value)}
                  className="w-full border px-3 py-2 text-sm"
                />
              </label>
            </div>

            <div className="announce-fields announce-fields--pair">
              <div className="announce-field">
                <span className="announce-field-label" id="announce-category-label">分类</span>
                <div role="group" aria-labelledby="announce-category-label" className="orbit-segmented orbit-segmented--accent announce-segmented">
                  {ANNOUNCEMENT_CATEGORIES.map((category) => (
                    <button
                      key={category}
                      type="button"
                      aria-pressed={draft.category === category}
                      onClick={() => setField("category", category)}
                    >
                      {ANNOUNCEMENT_CATEGORY_LABELS[category]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="announce-field">
                <span className="announce-field-label" id="announce-severity-label">级别</span>
                <div role="group" aria-labelledby="announce-severity-label" className="orbit-segmented announce-segmented">
                  {ANNOUNCEMENT_SEVERITIES.map((severity) => (
                    <button
                      key={severity}
                      type="button"
                      data-severity={severity}
                      aria-pressed={draft.severity === severity}
                      onClick={() => setField("severity", severity)}
                    >
                      <span className="announce-dot" data-severity={severity} aria-hidden="true" />
                      {ANNOUNCEMENT_SEVERITY_LABELS[severity]}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <label className="announce-field">
              <span className="announce-field-label">摘要<em aria-hidden="true">*</em></span>
              <textarea
                aria-label="公告摘要"
                value={draft.summary}
                placeholder="一两句话概括本次公告"
                onChange={(event) => setField("summary", event.target.value)}
                rows={2}
                className="w-full border px-3 py-2 text-sm"
              />
            </label>

            <div className="announce-field">
              <div className="announce-sections-head">
                <span className="announce-field-label">内容段落</span>
                <span className="announce-field-hint">每行一个条目，空段落不会发布</span>
              </div>
              {draft.sections.length ? (
                <ol className="announce-sections">
                  {draft.sections.map((section, index) => {
                    // Only flag content that would be lost; an untouched suggested heading is not an error.
                    const missingLabel = !section.label.trim() && sectionItems(section).length > 0;
                    return (
                      <li key={section.key} className="announce-section">
                        <div className="announce-section-head">
                          <span className="announce-section-index" aria-hidden="true">{index + 1}</span>
                          <input
                            aria-label={`公告段落 ${index + 1} 标题`}
                            value={section.label}
                            placeholder="段落标题，如：新增"
                            onChange={(event) => updateSection(section.key, { label: event.target.value })}
                            className="min-w-0 flex-1 border px-3 py-1.5 text-sm"
                          />
                          <button
                            type="button"
                            aria-label={`移除公告段落 ${index + 1}`}
                            onClick={() => removeSection(section.key)}
                            className="orbit-btn orbit-btn--ghost orbit-btn--icon orbit-btn--sm"
                          >
                            <X className="h-4 w-4" aria-hidden="true" />
                          </button>
                        </div>
                        <textarea
                          aria-label={`公告段落 ${index + 1} 条目`}
                          value={section.itemsText}
                          placeholder={"每行一个条目\n例如：新增权限管理入口"}
                          onChange={(event) => updateSection(section.key, { itemsText: event.target.value })}
                          rows={3}
                          className="w-full border px-3 py-2 text-sm"
                        />
                        {missingLabel ? (
                          <p className="announce-section-hint">缺少段落标题，发布时会忽略此段落</p>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              ) : null}
              <button type="button" onClick={addSection} className="orbit-btn orbit-btn--ghost orbit-btn--sm announce-add-section">
                <Plus className="h-4 w-4" aria-hidden="true" />
                添加段落
              </button>
            </div>
          </div>

          <aside className="announce-preview" aria-label="公告预览">
            <div className="announce-preview-head">
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
              <span>预览</span>
              <span className="announce-preview-note">与用户看到的一致</span>
            </div>
            <div className="announce-preview-body">
              <AnnouncementTimeline items={[previewItem]} />
            </div>
          </aside>
        </div>

        <footer className="announce-composer-foot">
          <p className="announce-foot-hint">
            {canPublish
              ? <>标题、摘要和条目支持 <code>&lt;strong&gt;</code>、<code>&lt;em&gt;</code>、<code>&lt;code&gt;</code> 等行内标记</>
              : `还需填写：${missing.join("、")}`}
          </p>
          <div className="announce-foot-actions">
            <button type="button" onClick={resetDraft} disabled={saving} className="orbit-btn orbit-btn--ghost">
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              清空
            </button>
            <button
              type="button"
              onClick={onPublish}
              disabled={saving || !canPublish}
              className="orbit-btn orbit-btn--primary"
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {saving ? "发布中..." : "发布公告"}
            </button>
          </div>
        </footer>
      </section>

      <section aria-labelledby="announce-history-title" className="admin-island orbit-island orbit-island--reading announce-history">
        <header className="announce-head">
          <span className="announce-head-icon" aria-hidden="true"><History className="h-4 w-4" /></span>
          <div className="announce-head-copy">
            <h2 id="announce-history-title">已发布</h2>
            <p>按发布时间倒序；删除后用户将不再看到该公告</p>
          </div>
          <span className="orbit-chip announce-count">共 {items.length} 条</span>
        </header>

        {items.length ? (
          <ol className="announce-list">
            {items.map((item, index) => {
              const deleting = deletingId === item.id;
              return (
                <li key={item.id} className="announce-row" data-severity={item.severity} aria-busy={deleting || undefined}>
                  <div className="announce-row-body">
                    <div className="announce-row-tags">
                      <span className="orbit-chip" data-tone={item.severity}>
                        <span className="announce-dot" data-severity={item.severity} aria-hidden="true" />
                        {ANNOUNCEMENT_SEVERITY_LABELS[item.severity]}
                      </span>
                      <span className="orbit-chip" data-tone="accent">{ANNOUNCEMENT_CATEGORY_LABELS[item.category]}</span>
                      {index === 0 ? <span className="orbit-chip">最新</span> : null}
                    </div>
                    <h3 className="announce-row-title">{renderSafeInlineHtml(item.title)}</h3>
                    <p className="announce-row-summary">{renderSafeInlineHtml(item.summary)}</p>
                    <div className="announce-row-meta">
                      <span>{item.publisher}</span>
                      <time dateTime={item.publishedAt}>{formatAnnouncementTime(item.publishedAt)}</time>
                      {item.sections.length ? <span>{item.sections.length} 个段落</span> : null}
                      <code title="公告 ID">{item.id}</code>
                    </div>
                  </div>
                  <button
                    type="button"
                    aria-label={`删除公告：${plainText(item.title) || item.id}`}
                    onClick={() => onDelete(item.id)}
                    disabled={deleting}
                    className="orbit-btn orbit-btn--sm admin-btn--danger-quiet announce-row-delete"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    {deleting ? "删除中..." : "删除"}
                  </button>
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="announce-empty">
            <Inbox className="h-6 w-6" aria-hidden="true" />
            <p>还没有发布过公告</p>
            <span>在上方撰写第一条公告</span>
          </div>
        )}
      </section>
    </div>
  );
}
