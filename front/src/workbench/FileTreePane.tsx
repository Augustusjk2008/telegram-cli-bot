import { clsx } from "clsx";
import {
  Check,
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  FilePlus,
  FolderOpen,
  FolderPlus,
  FolderTree,
  GitBranch,
  House,
  ListTree,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";
import { type CSSProperties, type DragEvent, type KeyboardEvent, type MouseEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FileNameDialog } from "../components/FileNameDialog";
import { VirtualList } from "../components/virtual/VirtualList";
import type { GitTreeDecorationKind, RemoteWorkspace } from "../services/types";
import { joinRemotePath } from "../services/remoteWorkspace";
import type { UiThemeName } from "../theme";
import { PAPER_STYLE } from "../theme/types";
import { isAbsolutePathInput } from "../utils/pathInput";
import { deletePathWithReadonlyConfirmation } from "../utils/deletePath";
import { FileIcon, FolderIcon, getFileIconKind, getFolderIconKind } from "./fileTreeIcons";
import { FILE_TREE_COMPACT_CHAIN_LIMIT, type FileTreeNode, type UseFileTreeResult } from "./useFileTree";

type Props = {
  tree: UseFileTreeResult;
  themeName?: UiThemeName;
  onOpenFile: (path: string) => void;
  onOpenFileToRight?: (path: string) => void;
  onCreatedFile: (path: string, content: string, lastModifiedNs?: string) => void;
  onRenamedFile: (oldPath: string, nextPath: string) => void;
  onDeletedFile: (path: string) => void;
  onRequestPreview: (path: string) => void;
  onRequestDiff?: (path: string, absolutePath: string) => void | Promise<void>;
  onRequestUpload: (files: File[], parentPath: string) => Promise<void>;
  onRequestHome: () => Promise<void>;
  onRequestNavigatePath?: (path: string) => Promise<void>;
  onRequestOpenSystemFolder?: () => Promise<void>;
  gitDecorations: Record<string, GitTreeDecorationKind>;
  onRefreshGitDecorations: () => Promise<void>;
  onRequestSetWorkdir: (path: string) => void;
  structureOnly?: boolean;
  canWriteFiles?: boolean;
  canBrowseExternalPaths?: boolean;
  remote?: boolean;
  remotePlatform?: RemoteWorkspace["platform"];
  focused: boolean;
  onToggleFocus: () => void;
};

type TreeContextMenuState = {
  entry: FileTreeNode;
  absolutePath: string;
  x: number;
  y: number;
};

type FileTreeVisibleRow =
  /** `chain` lists the directories merged in front of `entry` on a compact row, outermost first. */
  | { type: "entry"; entry: FileTreeNode; depth: number; chain: FileTreeNode[] }
  | { type: "status"; branchPath: string; depth: number; text: string; tone: "muted" | "error" };

type FileTreeViewOptions = {
  compactFolders: boolean;
  showGitDirectory: boolean;
};

const TREE_CONTEXT_MENU_WIDTH_PX = 152;
const TREE_CONTEXT_MENU_PADDING_PX = 8;
const INTERNAL_FILE_DRAG_TYPE = "application/x-tcb-file-path";
const ROOT_DROP_TARGET = "__root__";
const TREE_AUTO_SCROLL_EDGE_PX = 40;
const TREE_AUTO_SCROLL_MAX_STEP_PX = 18;
/** Horizontal step per tree level; the indent guides in workbench.css read it as `--file-tree-indent`. */
const TREE_INDENT_PX = 8;
const HIDDEN_GIT_ENTRY_NAME = ".git";
const FILE_TREE_VIEW_OPTIONS_STORAGE_KEY = "web-file-tree-view-options:v1";
const DEFAULT_FILE_TREE_VIEW_OPTIONS: FileTreeViewOptions = { compactFolders: true, showGitDirectory: false };

function readFileTreeViewOptions(): FileTreeViewOptions {
  try {
    const raw = JSON.parse(localStorage.getItem(FILE_TREE_VIEW_OPTIONS_STORAGE_KEY) || "{}");
    return {
      compactFolders: raw?.compactFolders !== false,
      showGitDirectory: raw?.showGitDirectory === true,
    };
  } catch {
    return DEFAULT_FILE_TREE_VIEW_OPTIONS;
  }
}

function writeFileTreeViewOptions(options: FileTreeViewOptions) {
  try {
    localStorage.setItem(FILE_TREE_VIEW_OPTIONS_STORAGE_KEY, JSON.stringify(options));
  } catch {
    // The choice still applies to this page.
  }
}

/** The child named by the listing hint of a directory whose branch has not been loaded. */
function hintedChildDirectory(entry: FileTreeNode): FileTreeNode | null {
  const [head, ...rest] = entry.compactChain ?? [];
  if (!head) {
    return null;
  }
  return {
    path: `${entry.path}/${head.name}`,
    name: head.name,
    isDir: true,
    childCount: head.childCount,
    ...(rest.length > 0 ? { compactChain: rest } : {}),
  };
}

/** The directory that is the only child of `entry`; a loaded branch outranks the listing hint. */
function onlyChildDirectory(entry: FileTreeNode, branches: UseFileTreeResult["branches"]): FileTreeNode | null {
  const branch = branches[entry.path];
  if (branch?.loaded) {
    const only = branch.entries.length === 1 ? branch.entries[0] : null;
    return only?.isDir ? only : null;
  }
  return hintedChildDirectory(entry);
}

/** Directories below `entry` that a compact row merges with it, outermost first. */
function resolveCompactChain(entry: FileTreeNode, branches: UseFileTreeResult["branches"]): FileTreeNode[] {
  const chain: FileTreeNode[] = [];
  let next = onlyChildDirectory(entry, branches);
  while (next && chain.length < FILE_TREE_COMPACT_CHAIN_LIMIT) {
    chain.push(next);
    next = onlyChildDirectory(next, branches);
  }
  return chain;
}

function workspaceBaseName(path: string, remote = false) {
  const trimmedPath = path.replace(remote ? /\/+$/ : /[\\/]+$/, "");
  const parts = trimmedPath.split(remote ? "/" : /[\\/]/);
  return parts[parts.length - 1] || path;
}

function formatFileSize(value: number) {
  if (!Number.isFinite(value) || value < 0) {
    return "--";
  }
  if (value < 1024) {
    return `${Math.floor(value)} B`;
  }

  const units = ["KB", "MB", "GB", "TB", "PB"];
  let scaled = value / 1024;
  let unitIndex = 0;
  while (scaled >= 1024 && unitIndex < units.length - 1) {
    scaled /= 1024;
    unitIndex += 1;
  }
  return `${Number(scaled.toFixed(1))} ${units[unitIndex]}`;
}

function fileTreeEntryMetadata(entry: FileTreeNode) {
  if (entry.isDir) {
    return typeof entry.childCount === "number" ? `${entry.childCount} 项` : "--";
  }
  return typeof entry.size === "number" ? formatFileSize(entry.size) : "--";
}

function clamp(value: number, min: number, max: number) {
  if (min > max) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

function joinAbsoluteTreePath(rootPath: string, path: string, remote = false, platform?: RemoteWorkspace["platform"]) {
  if (!path) {
    return rootPath;
  }
  if (remote) {
    return joinRemotePath(rootPath, path, platform);
  }
  const trimmedRoot = rootPath.replace(/[\\/]+$/, "");
  if (!trimmedRoot) {
    return path;
  }
  const separator = trimmedRoot.includes("\\") ? "\\" : "/";
  const normalizedPath = path.replace(/[\\/]+/g, separator);
  return `${trimmedRoot}${separator}${normalizedPath}`;
}

function resolveContextMenuPosition(x: number, y: number, isDir: boolean) {
  const estimatedHeight = isDir ? 204 : 224;
  return {
    x: clamp(x, TREE_CONTEXT_MENU_PADDING_PX, window.innerWidth - TREE_CONTEXT_MENU_WIDTH_PX - TREE_CONTEXT_MENU_PADDING_PX),
    y: clamp(y, TREE_CONTEXT_MENU_PADDING_PX, window.innerHeight - estimatedHeight - TREE_CONTEXT_MENU_PADDING_PX),
  };
}

function parentTreePath(path: string) {
  const lastSlash = path.lastIndexOf("/");
  return lastSlash >= 0 ? path.slice(0, lastSlash) : "";
}

function findTreeNodeByPath(
  rootEntries: FileTreeNode[],
  branches: UseFileTreeResult["branches"],
  path: string,
): FileTreeNode | null {
  const visit = (entries: FileTreeNode[]): FileTreeNode | null => {
    for (const entry of entries) {
      if (entry.path === path) {
        return entry;
      }
      if (!entry.isDir || !path.startsWith(`${entry.path}/`)) {
        continue;
      }
      const branch = branches[entry.path];
      // A directory merged into a compact row may be known only from its parent's listing hint.
      const hinted = branch?.loaded || branch?.entries.length ? null : hintedChildDirectory(entry);
      return visit(hinted ? [hinted] : branch?.entries || []);
    }
    return null;
  };

  return visit(rootEntries);
}

function dataTransferTypes(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer?.types || []);
}

function hasInternalTreeEntryDrag(event: DragEvent<HTMLElement>) {
  return dataTransferTypes(event).includes(INTERNAL_FILE_DRAG_TYPE);
}

function canMoveTreeEntryToDirectory(sourcePath: string, targetDirectoryPath: string) {
  if (!sourcePath || parentTreePath(sourcePath) === targetDirectoryPath) {
    return false;
  }
  if (sourcePath === targetDirectoryPath || targetDirectoryPath.startsWith(`${sourcePath}/`)) {
    return false;
  }
  return true;
}

function resolveGitDecoration(
  path: string,
  isDir: boolean,
  gitDecorations: Record<string, GitTreeDecorationKind>,
  inheritedDirDecorations: Record<string, GitTreeDecorationKind>,
) {
  const direct = gitDecorations[path];
  if (direct === "ignored" || direct === "added" || !isDir) {
    return direct;
  }
  return inheritedDirDecorations[path] || (direct === "modified" ? "modified" : undefined);
}

function treeItemToneClass(gitDecoration?: GitTreeDecorationKind) {
  if (gitDecoration === "ignored") {
    return "text-[var(--muted)]";
  }
  if (gitDecoration === "added") {
    return "text-[var(--status-success)]";
  }
  if (gitDecoration === "modified") {
    return "text-[var(--status-warning)]";
  }
  return "text-[var(--text)]";
}

export function FileTreePane({
  tree,
  themeName,
  onOpenFile,
  onOpenFileToRight,
  onCreatedFile,
  onRenamedFile,
  onDeletedFile,
  onRequestPreview,
  onRequestDiff,
  onRequestUpload,
  onRequestHome,
  onRequestNavigatePath,
  onRequestOpenSystemFolder,
  gitDecorations,
  onRefreshGitDecorations,
  onRequestSetWorkdir,
  structureOnly = false,
  canWriteFiles = true,
  canBrowseExternalPaths = false,
  remote = false,
  remotePlatform,
  focused,
  onToggleFocus,
}: Props) {
  const [createKind, setCreateKind] = useState<"file" | "directory" | null>(null);
  const [pendingName, setPendingName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [renameTargetPath, setRenameTargetPath] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState("");
  const [contextMenu, setContextMenu] = useState<TreeContextMenuState | null>(null);
  const [dragDepth, setDragDepth] = useState(0);
  const [draggedEntryPath, setDraggedEntryPath] = useState("");
  const [dropTargetPath, setDropTargetPath] = useState("");
  const [actionError, setActionError] = useState("");
  const [compressingPath, setCompressingPath] = useState("");
  const [showEntryMetadata, setShowEntryMetadata] = useState(false);
  const [viewOptions, setViewOptions] = useState(readFileTreeViewOptions);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [jumpBarOpen, setJumpBarOpen] = useState(false);
  const [externalPath, setExternalPath] = useState("");
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const moreMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const moreMenuRef = useRef<HTMLDivElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const contextMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const treeScrollRef = useRef<HTMLDivElement | null>(null);
  const treeScrollTopRef = useRef(0);
  const rowHeight = PAPER_STYLE.fileTreeRowHeight;
  const previousRowHeightRef = useRef<number | null>(null);
  const previousHighlightedPathRef = useRef("");
  const autoScrollFrameRef = useRef<number | null>(null);
  const autoScrollStepRef = useRef(0);
  const inheritedDirDecorations = useMemo(() => {
    const next: Record<string, GitTreeDecorationKind> = {};
    for (const [candidate, decoration] of Object.entries(gitDecorations)) {
      if (decoration !== "added" && decoration !== "modified") {
        continue;
      }
      const parts = candidate.split("/");
      if (parts.length <= 1) {
        continue;
      }
      let current = "";
      for (let index = 0; index < parts.length - 1; index += 1) {
        current = current ? `${current}/${parts[index]}` : parts[index];
        if (next[current] === "added") {
          continue;
        }
        next[current] = decoration === "added" ? "added" : next[current] || "modified";
      }
    }
    return next;
  }, [gitDecorations]);
  const contextMenuDecoration = contextMenu
    ? resolveGitDecoration(contextMenu.entry.path, contextMenu.entry.isDir, gitDecorations, inheritedDirDecorations)
    : undefined;
  const canPreviewFiles = !structureOnly;
  const canMutateFiles = canPreviewFiles && canWriteFiles;
  const canManageFiles = canMutateFiles && !remote;
  const canJumpToPath = canBrowseExternalPaths && !structureOnly;
  const { compactFolders, showGitDirectory } = viewOptions;

  function updateViewOptions(patch: Partial<FileTreeViewOptions>) {
    const next = { ...viewOptions, ...patch };
    setViewOptions(next);
    writeFileTreeViewOptions(next);
  }

  function closeJumpBar() {
    setJumpBarOpen(false);
    setExternalPath("");
  }

  function stopTreeAutoScroll() {
    autoScrollStepRef.current = 0;
    if (autoScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(autoScrollFrameRef.current);
      autoScrollFrameRef.current = null;
    }
  }

  function runTreeAutoScroll() {
    const viewport = treeScrollRef.current;
    const step = autoScrollStepRef.current;
    if (!viewport || step === 0) {
      autoScrollFrameRef.current = null;
      return;
    }
    const maxScrollTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
    const nextScrollTop = Math.max(0, Math.min(maxScrollTop, viewport.scrollTop + step));
    if (nextScrollTop === viewport.scrollTop) {
      stopTreeAutoScroll();
      return;
    }
    viewport.scrollTop = nextScrollTop;
    viewport.dispatchEvent(new Event("scroll", { bubbles: true }));
    autoScrollFrameRef.current = window.requestAnimationFrame(runTreeAutoScroll);
  }

  function updateTreeAutoScroll(event: DragEvent<HTMLElement>) {
    const viewport = treeScrollRef.current;
    if (!viewport) {
      return;
    }
    const rect = viewport.getBoundingClientRect();
    const topDistance = event.clientY - rect.top;
    const bottomDistance = rect.bottom - event.clientY;
    let nextStep = 0;
    if (topDistance >= 0 && topDistance < TREE_AUTO_SCROLL_EDGE_PX) {
      nextStep = -Math.ceil(((TREE_AUTO_SCROLL_EDGE_PX - topDistance) / TREE_AUTO_SCROLL_EDGE_PX) * TREE_AUTO_SCROLL_MAX_STEP_PX);
    } else if (bottomDistance >= 0 && bottomDistance < TREE_AUTO_SCROLL_EDGE_PX) {
      nextStep = Math.ceil(((TREE_AUTO_SCROLL_EDGE_PX - bottomDistance) / TREE_AUTO_SCROLL_EDGE_PX) * TREE_AUTO_SCROLL_MAX_STEP_PX);
    }
    autoScrollStepRef.current = nextStep;
    if (nextStep === 0) {
      stopTreeAutoScroll();
      return;
    }
    if (autoScrollFrameRef.current === null) {
      autoScrollFrameRef.current = window.requestAnimationFrame(runTreeAutoScroll);
    }
  }

  useEffect(() => () => stopTreeAutoScroll(), []);

  useEffect(() => {
    if (!moreMenuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (moreMenuButtonRef.current?.contains(target) || moreMenuRef.current?.contains(target)) {
        return;
      }
      setMoreMenuOpen(false);
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      event.preventDefault();
      setMoreMenuOpen(false);
      moreMenuButtonRef.current?.focus();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [moreMenuOpen]);

  function closeContextMenu() {
    setContextMenu(null);
  }

  useLayoutEffect(() => {
    if (!contextMenu || !contextMenuRef.current) return;
    const bounds = contextMenuRef.current.getBoundingClientRect();
    const x = clamp(contextMenu.x, TREE_CONTEXT_MENU_PADDING_PX, window.innerWidth - bounds.width - TREE_CONTEXT_MENU_PADDING_PX);
    const y = clamp(contextMenu.y, TREE_CONTEXT_MENU_PADDING_PX, window.innerHeight - bounds.height - TREE_CONTEXT_MENU_PADDING_PX);
    if (x !== contextMenu.x || y !== contextMenu.y) {
      setContextMenu({ ...contextMenu, x, y });
    }
  }, [contextMenu]);

  useEffect(() => {
    if (!contextMenu) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setContextMenu(null);
      contextMenuTriggerRef.current?.focus();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [contextMenu]);

  function resetInternalDrag() {
    stopTreeAutoScroll();
    setDraggedEntryPath("");
    setDropTargetPath("");
  }

  function openRenameDialog(path: string, name: string) {
    setRenameTargetPath(path);
    setRenameValue(name);
    setRenameError("");
    setShowRenameDialog(true);
  }

  function openContextMenu(entry: FileTreeNode, absolutePath: string, x: number, y: number) {
    const position = resolveContextMenuPosition(x, y, entry.isDir);
    setContextMenu({
      entry,
      absolutePath,
      x: position.x,
      y: position.y,
    });
  }

  function resolveSelectedDirectoryPath() {
    const selectedPath = tree.selectedPath;
    if (!selectedPath) {
      return "";
    }
    const selectedNode = findTreeNodeByPath(tree.rootEntries, tree.branches, selectedPath);
    return selectedNode?.isDir ? selectedPath : "";
  }

  function handleEntryContextMenu(event: MouseEvent<HTMLButtonElement>, entry: FileTreeNode, absolutePath: string) {
    if (!canPreviewFiles) {
      return;
    }
    event.preventDefault();
    contextMenuTriggerRef.current = event.currentTarget;
    tree.selectPath(entry.path);
    openContextMenu(entry, absolutePath, event.clientX, event.clientY);
  }

  function handleEntryContextMenuKey(event: KeyboardEvent<HTMLButtonElement>, entry: FileTreeNode, absolutePath: string) {
    if (!canPreviewFiles) {
      return;
    }
    if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) {
      return;
    }
    event.preventDefault();
    contextMenuTriggerRef.current = event.currentTarget;
    tree.selectPath(entry.path);
    const rect = event.currentTarget.getBoundingClientRect();
    openContextMenu(entry, absolutePath, rect.left + 12, rect.bottom + 4);
  }

  function openCreateDialog(kind: "file" | "directory") {
    setPendingName("");
    setCreateError("");
    setCreateKind(kind);
  }

  async function handleCreateEntry() {
    if (!canMutateFiles) {
      setCreateError("无文件写入权限");
      return;
    }
    setCreateBusy(true);
    setCreateError("");
    setActionError("");
    try {
      if (createKind === "directory") {
        await tree.createDirectory(pendingName.trim(), resolveSelectedDirectoryPath());
      } else {
        const result = await tree.createFile(pendingName.trim(), "", resolveSelectedDirectoryPath());
        onCreatedFile(result.path, "", result.lastModifiedNs);
      }
      setCreateKind(null);
      setPendingName("");
      await onRefreshGitDecorations();
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : createKind === "directory" ? "新建文件夹失败" : "新建文件失败");
    } finally {
      setCreateBusy(false);
    }
  }

  async function handleRenameFile() {
    if (!canManageFiles) {
      setRenameError("无文件写入权限");
      return;
    }
    setRenameBusy(true);
    setRenameError("");
    setActionError("");
    try {
      const result = await tree.renameFile(renameTargetPath, renameValue.trim());
      closeContextMenu();
      setShowRenameDialog(false);
      setRenameTargetPath("");
      setRenameValue("");
      onRenamedFile(result.oldPath, result.path);
      await onRefreshGitDecorations();
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "重命名失败");
    } finally {
      setRenameBusy(false);
    }
  }

  async function handleDelete(entry: FileTreeNode) {
    if (!canManageFiles) {
      setActionError("无文件写入权限");
      return;
    }
    const message = entry.isDir
      ? `确定删除文件夹 ${entry.path} 吗？此操作会递归删除其中的所有内容。`
      : `确定删除文件 ${entry.path} 吗？`;
    if (!window.confirm(message)) {
      return;
    }

    setActionError("");
    try {
      if (!await deletePathWithReadonlyConfirmation((options) => tree.deletePath(entry.path, options))) {
        return;
      }
      onDeletedFile(entry.path);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "删除失败");
    }
  }

  async function handleCopyFile(path: string) {
    if (!canManageFiles) {
      setActionError("无文件写入权限");
      return;
    }
    setActionError("");
    try {
      await tree.copyFile(path);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "复制失败");
    }
  }

  async function handleCompressDirectory(entry: FileTreeNode) {
    if (!canManageFiles || !entry.isDir || compressingPath) {
      return;
    }
    setCompressingPath(entry.path);
    setActionError("");
    try {
      await tree.compressDirectory(entry.path);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "压缩文件夹失败");
    } finally {
      setCompressingPath("");
    }
  }

  async function handleCopyPath(path: string) {
    setActionError("");
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("当前环境不支持剪贴板复制");
      }
      await navigator.clipboard.writeText(path);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "复制路径失败");
    }
  }

  async function handleMoveFile(path: string, targetParentPath: string) {
    if (!canManageFiles) {
      setActionError("无文件写入权限");
      resetInternalDrag();
      return;
    }
    if (!canMoveTreeEntryToDirectory(path, targetParentPath)) {
      return;
    }
    setActionError("");
    try {
      const result = await tree.moveFile(path, targetParentPath);
      onRenamedFile(result.oldPath, result.path);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "移动失败");
    } finally {
      resetInternalDrag();
    }
  }

  function handleEntryDragStart(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (!canManageFiles) {
      event.preventDefault();
      return;
    }
    setDraggedEntryPath(entry.path);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(INTERNAL_FILE_DRAG_TYPE, entry.path);
    event.dataTransfer.setData("text/plain", entry.path);
  }

  function handleDirectoryDragOver(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (!canManageFiles || !entry.isDir || !hasInternalTreeEntryDrag(event)) {
      return;
    }
    updateTreeAutoScroll(event);
    const sourcePath = draggedEntryPath || event.dataTransfer.getData(INTERNAL_FILE_DRAG_TYPE);
    event.stopPropagation();
    if (!canMoveTreeEntryToDirectory(sourcePath, entry.path)) {
      event.dataTransfer.dropEffect = "none";
      setDropTargetPath((current) => current === entry.path ? "" : current);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTargetPath(entry.path);
  }

  function handleDirectoryDragLeave(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (!hasInternalTreeEntryDrag(event)) {
      return;
    }
    const relatedTarget = event.relatedTarget;
    if (relatedTarget instanceof Node && event.currentTarget.contains(relatedTarget)) {
      return;
    }
    setDropTargetPath((current) => current === entry.path ? "" : current);
  }

  function handleDirectoryDrop(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (!hasInternalTreeEntryDrag(event)) {
      return;
    }
    event.stopPropagation();
    if (!canManageFiles || !entry.isDir) {
      return;
    }
    const sourcePath = event.dataTransfer.getData(INTERNAL_FILE_DRAG_TYPE);
    if (!canMoveTreeEntryToDirectory(sourcePath, entry.path)) {
      resetInternalDrag();
      return;
    }
    event.preventDefault();
    void handleMoveFile(sourcePath, entry.path);
  }

  function internalDragSourcePath(event: DragEvent<HTMLElement>) {
    return draggedEntryPath || event.dataTransfer.getData(INTERNAL_FILE_DRAG_TYPE);
  }

  function handleRootDragOver(event: DragEvent<HTMLElement>) {
    if (!canManageFiles || !hasInternalTreeEntryDrag(event)) {
      return false;
    }
    const sourcePath = internalDragSourcePath(event);
    if (!canMoveTreeEntryToDirectory(sourcePath, "")) {
      event.dataTransfer.dropEffect = "none";
      setDropTargetPath("");
      return true;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTargetPath(ROOT_DROP_TARGET);
    updateTreeAutoScroll(event);
    return true;
  }

  function handleTreeDragLeave(event: DragEvent<HTMLElement>) {
    if (!hasInternalTreeEntryDrag(event)) {
      return;
    }
    const relatedTarget = event.relatedTarget;
    if (relatedTarget instanceof Node && event.currentTarget.contains(relatedTarget)) {
      return;
    }
    stopTreeAutoScroll();
  }

  function handleRootDrop(event: DragEvent<HTMLElement>) {
    if (!hasInternalTreeEntryDrag(event)) {
      return false;
    }
    event.preventDefault();
    const sourcePath = internalDragSourcePath(event);
    if (canManageFiles && canMoveTreeEntryToDirectory(sourcePath, "")) {
      void handleMoveFile(sourcePath, "");
      return true;
    }
    resetInternalDrag();
    return true;
  }

  async function handleUpload(files: File[]) {
    if (files.length === 0) {
      return;
    }
    if (!canMutateFiles) {
      setActionError("无文件写入权限");
      return;
    }
    setActionError("");
    try {
      await onRequestUpload(files, resolveSelectedDirectoryPath());
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "上传失败");
    }
  }

  async function handleRefresh() {
    setActionError("");
    await tree.refreshRoot({ preserveExpandedPaths: true });
    await onRefreshGitDecorations();
  }

  async function handleHome() {
    setActionError("");
    try {
      await onRequestHome();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "返回工作目录失败");
    }
  }

  async function handleNavigateExternalPath() {
    const path = externalPath.trim();
    if (!path) {
      setActionError("请输入绝对目录路径");
      return;
    }
    if (!isAbsolutePathInput(path)) {
      setActionError("请输入绝对目录路径");
      return;
    }
    if (!onRequestNavigatePath) {
      return;
    }
    setActionError("");
    try {
      await onRequestNavigatePath(path);
      closeJumpBar();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "跳转目录失败");
    }
  }

  async function handleOpenSystemFolder() {
    if (!onRequestOpenSystemFolder) {
      return;
    }
    setActionError("");
    try {
      await onRequestOpenSystemFolder();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "打开系统文件夹失败");
    }
  }

  function flattenBranch(entries: FileTreeNode[], depth: number): FileTreeVisibleRow[] {
    const rows: FileTreeVisibleRow[] = [];
    for (const first of entries) {
      if (!showGitDirectory && first.name === HIDDEN_GIT_ENTRY_NAME) {
        continue;
      }
      // A compact row stands for its innermost directory; the ones in front of it only add to the label.
      const merged = first.isDir && compactFolders ? resolveCompactChain(first, tree.branches) : [];
      const entry = merged.length > 0 ? merged[merged.length - 1] : first;
      rows.push({ type: "entry", entry, depth, chain: merged.length > 0 ? [first, ...merged.slice(0, -1)] : [] });
      if (!entry.isDir || !tree.isExpanded(entry.path)) {
        continue;
      }
      const branch = tree.branches[entry.path];
      if (branch?.loading) {
        rows.push({ type: "status", branchPath: entry.path, depth: depth + 1, text: "加载中...", tone: "muted" });
      }
      if (branch?.error) {
        rows.push({ type: "status", branchPath: entry.path, depth: depth + 1, text: branch.error, tone: "error" });
      }
      if (branch?.entries?.length) {
        rows.push(...flattenBranch(branch.entries, depth + 1));
      }
    }
    return rows;
  }

  function renderTreeRow(row: FileTreeVisibleRow) {
    if (row.type === "status") {
      return (
        <div
          className={clsx("flex h-full items-center px-1 text-[11px]", row.tone === "error" ? "text-[var(--status-danger)]" : "text-[var(--muted)]")}
          style={{ height: rowHeight, paddingLeft: `${row.depth * TREE_INDENT_PX + 36}px` }}
        >
          {row.text}
        </div>
      );
    }

    const { entry, depth, chain } = row;
    const expanded = tree.isExpanded(entry.path);
    const absolutePathOf = (node: FileTreeNode) => joinAbsoluteTreePath(tree.rootPath, node.path, remote, remotePlatform);
    const absolutePath = absolutePathOf(entry);
    const segments = [...chain, entry];
    const folderKind = segments.map((node) => getFolderIconKind(node.name)).find((kind) => kind !== "default") ?? "default";
    const gitDecoration = chain.some((node) => gitDecorations[node.path] === "ignored")
      ? "ignored"
      : resolveGitDecoration(entry.path, entry.isDir, gitDecorations, inheritedDirDecorations);
    const isIgnored = gitDecoration === "ignored";
    const itemToneClass = treeItemToneClass(gitDecoration);
    const selected = segments.some((node) => node.path === tree.selectedPath);
    // Right-clicking one name of a compact row targets that directory instead of the innermost one.
    const contextTarget = (event: MouseEvent<HTMLButtonElement>) => {
      const segmentPath = event.target instanceof Element
        ? event.target.closest("[data-chain-path]")?.getAttribute("data-chain-path")
        : null;
      return chain.find((node) => node.path === segmentPath) ?? entry;
    };
    const metadata = fileTreeEntryMetadata(entry);
    const itemButtonClassName = clsx(
      "file-tree-row-button relative flex h-full min-w-0 flex-1 items-center pr-1 text-left",
    );

    return (
      <div
        className="file-tree-row group relative flex h-full min-w-0 items-center text-[13px]"
        style={{ height: rowHeight }}
        data-tree-path={entry.path}
        data-compact={chain.length > 0 ? "true" : "false"}
        data-git-state={gitDecoration || "clean"}
        data-git-ignored={isIgnored ? "true" : "false"}
        data-highlighted={tree.highlightedPath === entry.path ? "true" : "false"}
        data-selected={selected ? "true" : "false"}
        data-drop-target={dropTargetPath === entry.path ? "true" : "false"}
      >
        {depth > 0 ? (
          <span
            aria-hidden="true"
            className="file-tree-indent-guides pointer-events-none absolute inset-y-0 left-0"
            style={{ width: `${depth * TREE_INDENT_PX}px` }}
          />
        ) : null}
        {entry.isDir ? (
          <button
            type="button"
            draggable={canManageFiles}
            aria-label={`${expanded ? "收起" : "展开"} ${entry.path}`}
            aria-expanded={expanded}
            aria-current={selected ? "true" : undefined}
            title={absolutePath}
            onContextMenu={(event) => {
              const target = contextTarget(event);
              handleEntryContextMenu(event, target, absolutePathOf(target));
            }}
            onKeyDown={(event) => handleEntryContextMenuKey(event, entry, absolutePath)}
            onDragStart={(event) => handleEntryDragStart(event, entry)}
            onDragOver={(event) => handleDirectoryDragOver(event, entry)}
            onDragLeave={(event) => handleDirectoryDragLeave(event, entry)}
            onDrop={(event) => handleDirectoryDrop(event, entry)}
            onDragEnd={resetInternalDrag}
            onClick={() => {
              if (tree.selectedPath === entry.path) {
                tree.clearSelection();
              } else {
                tree.selectPath(entry.path);
              }
              void tree.toggleDirectory(entry.path, { followSingleChildDirectories: compactFolders });
            }}
            className={clsx(
              itemButtonClassName,
              dropTargetPath === entry.path && "bg-[var(--accent-soft)] outline outline-1 outline-[var(--accent)]",
            )}
          >
            <span
              className="flex w-full min-w-0 items-center gap-1"
              style={{ paddingLeft: `${depth * TREE_INDENT_PX + 2}px` }}
            >
              {expanded
                ? <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0 text-[var(--muted)]" />
                : <ChevronRight aria-hidden="true" className="h-3 w-3 shrink-0 text-[var(--muted)]" />}
              <FolderIcon kind={folderKind} open={expanded} />
              <span className={clsx("min-w-0 flex-1 truncate font-normal", itemToneClass)}>
                {chain.map((node) => (
                  <span key={node.path}>
                    <span
                      data-chain-path={node.path}
                      className={clsx(node.path === tree.selectedPath && "underline underline-offset-2")}
                    >
                      {node.name}
                    </span>
                    <span aria-hidden="true" className="px-px opacity-55">/</span>
                  </span>
                ))}
                {entry.name}
              </span>
              {showEntryMetadata ? (
                <span className="ml-1 shrink-0 text-[11px] font-normal tabular-nums text-[var(--muted)]">
                  {metadata}
                </span>
              ) : null}
            </span>
          </button>
        ) : (
          <button
            type="button"
            draggable={canManageFiles}
            aria-label={`打开 ${entry.path}`}
            aria-current={selected ? "true" : undefined}
            title={absolutePath}
            onContextMenu={(event) => handleEntryContextMenu(event, entry, absolutePath)}
            onKeyDown={(event) => handleEntryContextMenuKey(event, entry, absolutePath)}
            onDragStart={(event) => handleEntryDragStart(event, entry)}
            onDragEnd={resetInternalDrag}
            onClick={() => {
              tree.selectPath(entry.path);
              if (canPreviewFiles) {
                onOpenFile(entry.path);
              }
            }}
            className={itemButtonClassName}
          >
            <span
              className="flex w-full min-w-0 items-center gap-1"
              style={{ paddingLeft: `${depth * TREE_INDENT_PX + 2}px` }}
            >
              <span aria-hidden="true" className="h-3 w-3 shrink-0" />
              <FileIcon kind={getFileIconKind(entry.name)} />
              <span className={clsx("min-w-0 flex-1 truncate font-normal", itemToneClass)}>{entry.name}</span>
              {showEntryMetadata ? (
                <span className="ml-1 shrink-0 text-[11px] font-normal tabular-nums text-[var(--muted)]">
                  {metadata}
                </span>
              ) : null}
            </span>
          </button>
        )}
      </div>
    );
  }

  const visibleTreeRows = useMemo(
    () => (!tree.loading && !tree.error ? flattenBranch(tree.rootEntries, 0) : []),
    [tree.loading, tree.error, tree.rootEntries, tree.branches, tree.expandedPaths, compactFolders, showGitDirectory],
  );

  // Restore selection when returning from settings; density changes retain the row anchor.
  useLayoutEffect(() => {
    const previousRowHeight = previousRowHeightRef.current;
    const viewport = treeScrollRef.current;
    if (!viewport || visibleTreeRows.length === 0) {
      return;
    }
    const revealChanged = Boolean(tree.highlightedPath) && previousHighlightedPathRef.current !== tree.highlightedPath;
    previousRowHeightRef.current = rowHeight;
    previousHighlightedPathRef.current = tree.highlightedPath;
    if (previousRowHeight === rowHeight && !revealChanged) return;

    const viewportHeight = viewport.clientHeight;
    let nextScrollTop = previousRowHeight === null ? viewport.scrollTop : treeScrollTopRef.current / previousRowHeight * rowHeight;
    const targetPath = revealChanged ? tree.highlightedPath : tree.selectedPath;
    const selectedIndex = visibleTreeRows.findIndex((row) => (
      row.type === "entry" && (row.entry.path === targetPath || row.chain.some((node) => node.path === targetPath))
    ));
    if (selectedIndex >= 0 && viewportHeight > 0) {
      const selectedTop = selectedIndex * rowHeight;
      if (selectedTop < nextScrollTop) {
        nextScrollTop = selectedTop;
      } else if (selectedTop + rowHeight > nextScrollTop + viewportHeight) {
        nextScrollTop = selectedTop + rowHeight - viewportHeight;
      }
    }
    viewport.scrollTop = Math.max(0, Math.min(nextScrollTop, visibleTreeRows.length * rowHeight - viewportHeight));
    viewport.dispatchEvent(new Event("scroll", { bubbles: true }));
  }, [rowHeight, tree.selectedPath, tree.highlightedPath, visibleTreeRows]);

  return (
    <div
      data-testid="desktop-file-tree-dropzone"
      onDragEnter={(event) => {
        if (hasInternalTreeEntryDrag(event)) {
          return;
        }
        if (!canMutateFiles) {
          return;
        }
        event.preventDefault();
        setDragDepth((current) => current + 1);
      }}
      onDragOver={(event) => {
        if (handleRootDragOver(event)) {
          return;
        }
        if (hasInternalTreeEntryDrag(event)) {
          return;
        }
        if (!canMutateFiles) {
          return;
        }
        event.preventDefault();
      }}
      onDragLeave={(event) => {
        if (hasInternalTreeEntryDrag(event)) {
          const relatedTarget = event.relatedTarget;
          if (relatedTarget instanceof Node && event.currentTarget.contains(relatedTarget)) {
            return;
          }
          resetInternalDrag();
          return;
        }
        event.preventDefault();
        setDragDepth((current) => Math.max(0, current - 1));
      }}
      onDrop={(event) => {
        if (handleRootDrop(event)) {
          return;
        }
        event.preventDefault();
        if (!canMutateFiles) {
          return;
        }
        setDragDepth(0);
        const files = Array.from(event.dataTransfer?.files || []);
        if (files.length > 0) {
          void handleUpload(files);
        }
      }}
      className="desktop-file-tree-pane relative flex h-full min-h-0 flex-col"
      style={{ "--file-tree-indent": `${TREE_INDENT_PX}px` } as CSSProperties}
    >
      <div className="file-tree-header relative flex h-[30px] shrink-0 items-center gap-1 border-b border-[var(--border)] px-1.5">
        <div
          aria-label={`工作区 ${tree.rootPath}`}
          title={tree.rootPath}
          className="file-tree-title min-w-0 flex-1 truncate px-1 text-[12px] font-medium text-[var(--text)]"
        >
          {workspaceBaseName(tree.rootPath, remote)}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {canMutateFiles ? (
            <>
              <input
                ref={uploadInputRef}
                aria-label="上传文件"
                type="file"
                className="hidden"
                onChange={(event) => {
                  const files = Array.from(event.target.files || []);
                  if (files.length > 0) {
                    void handleUpload(files);
                  }
                  event.currentTarget.value = "";
                }}
              />
              <button
                type="button"
                aria-label="新建文件"
                title="新建文件"
                onClick={() => openCreateDialog("file")}
                className="inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--workbench-focus-ring)]"
              >
                <FilePlus className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="新建文件夹"
                title="新建文件夹"
                onClick={() => openCreateDialog("directory")}
                className="inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--workbench-focus-ring)]"
              >
                <FolderPlus className="h-3.5 w-3.5" />
              </button>
            </>
          ) : null}
          <button
            type="button"
            aria-label="刷新文件树"
            title="刷新文件树"
            onClick={() => void handleRefresh()}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--workbench-focus-ring)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label={focused ? "退出聚焦文件区" : "聚焦文件区"}
            title={focused ? "退出聚焦文件区" : "聚焦文件区"}
            onClick={onToggleFocus}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--workbench-focus-ring)]"
          >
            {focused ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          <button
            ref={moreMenuButtonRef}
            type="button"
            aria-label="更多文件操作"
            aria-haspopup="menu"
            aria-expanded={moreMenuOpen}
            title="更多文件操作"
            onClick={() => setMoreMenuOpen((current) => !current)}
            className={clsx(
              "inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--workbench-focus-ring)]",
              moreMenuOpen && "bg-[var(--workbench-active-bg)] text-[var(--text)]",
            )}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
        </div>

        {moreMenuOpen ? (
          <div
            ref={moreMenuRef}
            role="menu"
            aria-label="更多文件操作"
            className="absolute right-1 top-full z-40 min-w-48 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]"
          >
            {canMutateFiles ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMoreMenuOpen(false);
                  uploadInputRef.current?.click();
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
              >
                <Upload className="h-3.5 w-3.5 text-[var(--muted)]" />
                上传文件
              </button>
            ) : null}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMoreMenuOpen(false);
                void handleHome();
              }}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
            >
              <House className="h-3.5 w-3.5 text-[var(--muted)]" />
              返回工作目录
            </button>
            {canJumpToPath ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMoreMenuOpen(false);
                  setJumpBarOpen(true);
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
              >
                <CornerDownRight className="h-3.5 w-3.5 text-[var(--muted)]" />
                跳转到路径…
              </button>
            ) : null}
            {canMutateFiles && onRequestOpenSystemFolder ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMoreMenuOpen(false);
                  void handleOpenSystemFolder();
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
              >
                <FolderOpen className="h-3.5 w-3.5 text-[var(--muted)]" />
                在系统文件夹中打开
              </button>
            ) : null}
            <button
              type="button"
              role="menuitemcheckbox"
              aria-checked={showEntryMetadata}
              onClick={() => {
                setShowEntryMetadata((current) => !current);
                setMoreMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
            >
              <ListTree className="h-3.5 w-3.5 text-[var(--muted)]" />
              {showEntryMetadata ? "隐藏条目信息" : "显示条目信息"}
            </button>
            <button
              type="button"
              role="menuitemcheckbox"
              aria-checked={compactFolders}
              title="只含一个子文件夹的文件夹与其子文件夹显示在同一行"
              onClick={() => {
                updateViewOptions({ compactFolders: !compactFolders });
                setMoreMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
            >
              <FolderTree className="h-3.5 w-3.5 text-[var(--muted)]" />
              <span className="min-w-0 flex-1">合并单一子文件夹</span>
              {compactFolders ? <Check aria-hidden="true" className="h-3.5 w-3.5 text-[var(--muted)]" /> : null}
            </button>
            <button
              type="button"
              role="menuitemcheckbox"
              aria-checked={showGitDirectory}
              onClick={() => {
                updateViewOptions({ showGitDirectory: !showGitDirectory });
                setMoreMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] hover:bg-[var(--workbench-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
            >
              <GitBranch className="h-3.5 w-3.5 text-[var(--muted)]" />
              <span className="min-w-0 flex-1">显示 .git</span>
              {showGitDirectory ? <Check aria-hidden="true" className="h-3.5 w-3.5 text-[var(--muted)]" /> : null}
            </button>
          </div>
        ) : null}
      </div>

      {canJumpToPath && jumpBarOpen ? (
        <form
          className="flex shrink-0 items-center gap-1 border-b border-[var(--border)] px-1.5 py-1"
          onSubmit={(event) => {
            event.preventDefault();
            void handleNavigateExternalPath();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              closeJumpBar();
              moreMenuButtonRef.current?.focus();
            }
          }}
        >
          <input
            autoFocus
            aria-label="跳转到绝对目录"
            value={externalPath}
            onChange={(event) => setExternalPath(event.target.value)}
            placeholder="直接跳转到路径"
            className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 text-[12px] text-[var(--text)] outline-none focus:border-[var(--accent)]"
          />
          <button
            type="submit"
            className="shrink-0 rounded border border-[var(--border)] px-2 py-0.5 text-[12px] text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
          >
            跳转
          </button>
          <button
            type="button"
            aria-label="关闭路径跳转"
            title="关闭"
            onClick={closeJumpBar}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </form>
      ) : null}

      <div
        data-testid="desktop-file-tree-scroll"
        data-root-drop-target={dropTargetPath === ROOT_DROP_TARGET ? "true" : "false"}
        onScrollCapture={(event) => {
          if (event.target === treeScrollRef.current) {
            treeScrollTopRef.current = treeScrollRef.current.scrollTop;
          }
        }}
        onClick={(event) => {
          const target = event.target;
          if (target instanceof Element && !target.closest("[data-tree-path]")) {
            tree.clearSelection();
          }
        }}
        className={clsx(
          "file-tree-scroll flex min-h-0 flex-1 flex-col px-1 py-1",
          dropTargetPath === ROOT_DROP_TARGET && "bg-[var(--accent-soft)] outline outline-1 outline-[var(--accent)]",
        )}
      >
        {compressingPath ? (
          <div role="status" className="px-3 py-2 text-xs text-[var(--muted)]">
            正在压缩 {compressingPath}…
          </div>
        ) : null}
        {actionError ? (
          <div className="mb-2 rounded border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-2 py-1.5 text-[12px] text-[var(--status-danger)]">
            {actionError}
          </div>
        ) : null}
        {tree.loading ? (
          <div className="px-2 py-2 text-[12px] text-[var(--muted)]">加载中...</div>
        ) : null}
        {!tree.loading && tree.error ? (
          <div className="px-2 py-2 text-[12px] text-[var(--status-danger)]">{tree.error}</div>
        ) : null}
        {!tree.loading && !tree.error ? (
          <VirtualList
            viewportRef={treeScrollRef}
            items={visibleTreeRows}
            rowHeight={rowHeight}
            className="flex-1"
            dataTestId="desktop-file-tree-virtual-list"
            onDragOver={(event) => {
              if (hasInternalTreeEntryDrag(event)) {
                updateTreeAutoScroll(event);
              }
            }}
            onDragLeave={handleTreeDragLeave}
            onDrop={(event) => {
              if (hasInternalTreeEntryDrag(event)) {
                stopTreeAutoScroll();
              }
            }}
            getKey={(row) => row.type === "entry" ? row.entry.path : `${row.branchPath}-${row.tone}`}
            renderRow={(row) => renderTreeRow(row)}
          />
        ) : null}
      </div>

      {contextMenu && typeof document !== "undefined"
        ? createPortal(
          <>
          <div
            className="fixed inset-0 z-20"
            onClick={closeContextMenu}
            onContextMenu={(event) => {
              event.preventDefault();
              closeContextMenu();
            }}
          />
          <div
            ref={contextMenuRef}
            role="menu"
            aria-label="文件树菜单"
            className="desktop-workbench-menu fixed z-30 min-w-36 max-h-[calc(100dvh-16px)] max-w-[calc(100vw-16px)] overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]"
            style={{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }}
            onContextMenu={(event) => {
              event.preventDefault();
            }}
          >
            {contextMenu.entry.isDir ? (
              <>
                <button
                  type="button"
                  onClick={() => {
                    void handleCopyPath(contextMenu.absolutePath);
                    closeContextMenu();
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  复制路径
                </button>
                {canManageFiles ? (
                  <button
                    type="button"
                    onClick={() => {
                      onRequestSetWorkdir(contextMenu.absolutePath);
                      closeContextMenu();
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    设为工作目录
                  </button>
                ) : null}
                {canManageFiles ? (
                  <button
                    type="button"
                    onClick={() => {
                      openRenameDialog(contextMenu.entry.path, contextMenu.entry.name);
                      closeContextMenu();
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    改名
                  </button>
                ) : null}
                {canManageFiles ? (
                  <button
                    type="button"
                    disabled={Boolean(compressingPath)}
                    onClick={() => {
                      const entry = contextMenu.entry;
                      closeContextMenu();
                      void handleCompressDirectory(entry);
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)] disabled:opacity-50"
                  >
                    压缩
                  </button>
                ) : null}
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => {
                    onRequestPreview(contextMenu.entry.path);
                    closeContextMenu();
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  预览
                </button>
                {onOpenFileToRight && !structureOnly ? (
                  <button
                    type="button"
                    onClick={() => {
                      onOpenFileToRight(contextMenu.entry.path);
                      closeContextMenu();
                    }}
                    className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    在右侧打开
                  </button>
                ) : null}
                {contextMenuDecoration === "modified" && onRequestDiff ? (
                  <button
                    type="button"
                    onClick={() => {
                      void onRequestDiff(contextMenu.entry.path, contextMenu.absolutePath);
                      closeContextMenu();
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    Diff
                  </button>
                ) : null}
                {canManageFiles ? (
                  <button
                    type="button"
                    onClick={() => {
                      openRenameDialog(contextMenu.entry.path, contextMenu.entry.name);
                      closeContextMenu();
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    改名
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    const path = contextMenu.absolutePath;
                    closeContextMenu();
                    void handleCopyPath(path);
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  复制路径
                </button>
                {canManageFiles ? (
                  <button
                    type="button"
                    onClick={() => {
                      const path = contextMenu.entry.path;
                      closeContextMenu();
                      void handleCopyFile(path);
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    复制
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    void tree.downloadFile(contextMenu.entry.path);
                    closeContextMenu();
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  下载
                </button>
              </>
            )}
            {canManageFiles ? (
              <button
                type="button"
                onClick={() => {
                  closeContextMenu();
                  void handleDelete(contextMenu.entry);
                }}
                className="flex w-full rounded-sm px-3 py-2 text-left text-sm text-[var(--status-danger)] hover:bg-[var(--status-danger-bg)]"
              >
                删除
              </button>
            ) : null}
          </div>
          </>,
          document.body,
        )
        : null}

      {canMutateFiles && dragDepth > 0 ? (
        <div
          data-testid="desktop-file-drop-overlay"
          className="pointer-events-none absolute inset-3 flex items-center justify-center rounded-2xl border border-dashed border-[var(--accent)] bg-[var(--accent-soft)] text-sm font-medium text-[var(--text)]"
        >
          {resolveSelectedDirectoryPath() ? `释放文件以上传到 ${resolveSelectedDirectoryPath()}` : "释放文件以上传到当前工作区根目录"}
        </div>
      ) : null}

      {canMutateFiles && createKind ? (
        <FileNameDialog
          title={createKind === "directory" ? "新建文件夹" : "新建文件"}
          label={createKind === "directory" ? "文件夹名" : "文件名"}
          value={pendingName}
          confirmText="创建"
          busy={createBusy}
          error={createError}
          onChange={setPendingName}
          onConfirm={() => void handleCreateEntry()}
          onClose={() => {
            if (createBusy) {
              return;
            }
            setCreateKind(null);
            setPendingName("");
            setCreateError("");
          }}
        />
      ) : null}

      {canManageFiles && showRenameDialog ? (
        <FileNameDialog
          title="重命名文件或文件夹"
          label="名称"
          value={renameValue}
          confirmText="重命名"
          busy={renameBusy}
          error={renameError}
          onChange={setRenameValue}
          onConfirm={() => void handleRenameFile()}
          onClose={() => {
            if (renameBusy) {
              return;
            }
            setShowRenameDialog(false);
            setRenameTargetPath("");
            setRenameValue("");
            setRenameError("");
          }}
        />
      ) : null}
    </div>
  );
}
