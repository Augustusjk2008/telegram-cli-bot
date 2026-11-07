import { clsx } from "clsx";
import {
  AudioWaveform,
  Binary,
  Clapperboard,
  CodeXml,
  Cpu,
  FileArchive,
  FileText,
  FolderTree,
  Presentation,
  Puzzle,
  Shapes,
  Sheet,
  Table2,
  Timer,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import type { PluginSummary } from "../../services/types";

type PluginIconSource = Pick<PluginSummary, "id" | "name" | "iconUrl" | "views" | "fileHandlers">;

type Glyph = { icon: LucideIcon; hue: string };

const FALLBACK_HUES = ["#3b82f6", "#8b5cf6", "#0d9488", "#d97706", "#db2777", "#0891b2", "#16a34a", "#6366f1"];

const ARCHIVE_EXTENSIONS = [".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".bz2"];
const MEDIA_EXTENSIONS = [".mp4", ".mp3", ".wav", ".webm", ".ogg", ".flac", ".m4a", ".aac"];
const HDL_EXTENSIONS = [".v", ".sv", ".vhd", ".vhdl", ".hier"];

type Rule = Glyph & { match: (id: string, extensions: Set<string>, renderers: Set<string>) => boolean };

function hasAny(extensions: Set<string>, candidates: string[]) {
  return candidates.some((extension) => extensions.has(extension));
}

// First match wins: specific formats before generic renderer categories.
const RULES: Rule[] = [
  { icon: FileText, hue: "#e5484d", match: (_id, ext) => ext.has(".pdf") },
  { icon: Workflow, hue: "#8b5cf6", match: (id, ext) => id.includes("mermaid") || ext.has(".mmd") },
  { icon: Sheet, hue: "#16a34a", match: (_id, ext) => hasAny(ext, [".xlsx", ".xls", ".csv"]) },
  { icon: Presentation, hue: "#ea580c", match: (_id, ext) => hasAny(ext, [".pptx", ".ppt"]) },
  { icon: FileText, hue: "#2563eb", match: (_id, ext) => hasAny(ext, [".docx", ".doc"]) },
  { icon: FileArchive, hue: "#d97706", match: (_id, ext) => hasAny(ext, ARCHIVE_EXTENSIONS) },
  { icon: Clapperboard, hue: "#db2777", match: (_id, ext, renderers) => renderers.has("media") || hasAny(ext, MEDIA_EXTENSIONS) },
  { icon: AudioWaveform, hue: "#0891b2", match: (_id, ext, renderers) => renderers.has("waveform") || ext.has(".vcd") },
  { icon: Binary, hue: "#6366f1", match: (_id, _ext, renderers) => renderers.has("hex") },
  { icon: Timer, hue: "#ca8a04", match: (id, ext) => id.includes("timing") || ext.has(".rpt") },
  { icon: Cpu, hue: "#0d9488", match: (id, ext) => /hdl|rtl/.test(id) || hasAny(ext, HDL_EXTENSIONS) },
  { icon: Shapes, hue: "#c026d3", match: (_id, ext) => ext.has(".svg") },
  { icon: CodeXml, hue: "#f97316", match: (_id, ext) => hasAny(ext, [".html", ".htm"]) },
  { icon: FolderTree, hue: "#0d9488", match: (_id, _ext, renderers) => renderers.has("tree") },
  { icon: Table2, hue: "#16a34a", match: (_id, _ext, renderers) => renderers.has("table") },
  { icon: FileText, hue: "#2563eb", match: (_id, _ext, renderers) => renderers.has("document") },
];

function hashHue(id: string) {
  let hash = 0;
  for (const char of id) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return FALLBACK_HUES[hash % FALLBACK_HUES.length];
}

export function resolvePluginGlyph(plugin: PluginIconSource): Glyph {
  const id = plugin.id.toLowerCase();
  const extensions = new Set(plugin.fileHandlers.flatMap((handler) => handler.extensions.map((ext) => ext.toLowerCase())));
  const renderers = new Set<string>(plugin.views.map((view) => view.renderer));
  const rule = RULES.find((item) => item.match(id, extensions, renderers));
  return rule ? { icon: rule.icon, hue: rule.hue } : { icon: Puzzle, hue: hashHue(id) };
}

type Props = {
  plugin: PluginIconSource;
  size?: "sm" | "md";
  muted?: boolean;
  className?: string;
};

export function PluginIcon({ plugin, size = "md", muted = false, className }: Props) {
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => setImageFailed(false), [plugin.iconUrl]);

  const glyph = resolvePluginGlyph(plugin);
  const Glyph = glyph.icon;
  const showImage = Boolean(plugin.iconUrl) && !imageFailed;
  const style = {
    "--plugin-hue": glyph.hue,
  } as CSSProperties;

  return (
    <span
      aria-hidden="true"
      data-testid={`plugin-icon-${plugin.id}`}
      data-icon-source={showImage ? "manifest" : "generated"}
      style={style}
      className={clsx(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden border transition-[filter,opacity]",
        size === "sm" ? "h-7 w-7 rounded-md" : "h-11 w-11 rounded-[10px]",
        showImage
          ? "border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)]"
          : "border-[color-mix(in_srgb,var(--plugin-hue)_28%,transparent)] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--plugin-hue)_22%,var(--workbench-panel-elevated-bg)),color-mix(in_srgb,var(--plugin-hue)_8%,var(--workbench-panel-elevated-bg)))] text-[var(--plugin-hue)]",
        muted && "opacity-60 grayscale",
        className,
      )}
    >
      {showImage ? (
        <img
          src={plugin.iconUrl}
          alt=""
          draggable={false}
          onError={() => setImageFailed(true)}
          className={clsx("object-contain", size === "sm" ? "h-5 w-5" : "h-8 w-8")}
        />
      ) : (
        <Glyph className={size === "sm" ? "h-4 w-4" : "h-[22px] w-[22px]"} strokeWidth={1.75} />
      )}
    </span>
  );
}
