import { useCallback, useEffect, useRef, useState } from "react";
import type { FileCopyResult, FileCreateResult, FileMoveResult, FileRenameResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { WORKBENCH_EXPANDED_PATH_RESTORE_LIMIT, WORKBENCH_HIGHLIGHT_DURATION_MS } from "./workbenchTypes";

export type FileTreeNode = {
  path: string;
  name: string;
  isDir: boolean;
  size?: number;
  updatedAt?: string;
};

type FileTreeBranchState = {
  entries: FileTreeNode[];
  loading: boolean;
  loaded: boolean;
  error: string;
};

export type UseFileTreeResult = {
  rootPath: string;
  loading: boolean;
  error: string;
  rootEntries: FileTreeNode[];
  branches: Record<string, FileTreeBranchState>;
  expandedPaths: string[];
  highlightedPath: string;
  selectedPath: string;
  selectPath: (path: string) => void;
  clearSelection: () => void;
  isExpanded: (path: string) => boolean;
  toggleDirectory: (path: string) => Promise<void>;
  refreshRoot: (options?: { preserveExpandedPaths?: boolean }) => Promise<void>;
  restoreExpandedPaths: (paths: string[]) => Promise<void>;
  revealPath: (path: string) => Promise<void>;
  highlightPath: (path: string) => void;
  createDirectory: (name: string, parentPath?: string) => Promise<void>;
  createFile: (filename: string, content?: string, parentPath?: string) => Promise<FileCreateResult>;
  renameFile: (path: string, newName: string) => Promise<FileRenameResult>;
  copyFile: (path: string) => Promise<FileCopyResult>;
  moveFile: (path: string, targetParentPath: string) => Promise<FileMoveResult>;
  deletePath: (path: string) => Promise<void>;
  downloadFile: (path: string) => Promise<void>;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function joinTreePath(parent: string, name: string) {
  return parent ? `${parent}/${name}` : name;
}

function joinAbsoluteTreePath(rootPath: string, path: string) {
  if (!path) {
    return rootPath;
  }
  return `${rootPath.replace(/[\\/]+$/, "")}/${path}`;
}

function parentTreePath(path: string) {
  const lastSlash = path.lastIndexOf("/");
  return lastSlash >= 0 ? path.slice(0, lastSlash) : "";
}

function isSameOrDescendantPath(path: string, parentPath: string) {
  return path === parentPath || path.startsWith(`${parentPath}/`);
}

function branchEntriesForPath(
  branchMap: Record<string, FileTreeBranchState>,
  parentPath: string,
) {
  return branchMap[parentPath]?.entries || [];
}

function branchMapContainsPath(
  branchMap: Record<string, FileTreeBranchState>,
  path: string,
) {
  if (!path) {
    return false;
  }
  const parentPath = parentTreePath(path);
  return branchEntriesForPath(branchMap, parentPath).some((entry) => entry.path === path);
}

function mapBranchEntries(parentPath: string, entries: Array<{ name: string; isDir: boolean; size?: number; updatedAt?: string }>) {
  return entries.map((entry) => ({
    path: joinTreePath(parentPath, entry.name),
    name: entry.name,
    isDir: entry.isDir,
    size: entry.size,
    updatedAt: entry.updatedAt,
  }));
}

function uniqueExpandedPaths(paths: string[]) {
  const seen = new Set<string>();
  return paths
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
    .filter((item) => {
      if (seen.has(item)) {
        return false;
      }
      seen.add(item);
      return true;
    })
    .sort((left, right) => left.split("/").length - right.split("/").length)
    .slice(0, WORKBENCH_EXPANDED_PATH_RESTORE_LIMIT);
}

function ancestorPathsForPath(path: string) {
  const ancestors: string[] = [];
  let current = parentTreePath(path);
  while (current) {
    ancestors.unshift(current);
    current = parentTreePath(current);
  }
  return ancestors;
}

export function useFileTree(botAlias: string, client: WebBotClient, options?: { structureOnly?: boolean }): UseFileTreeResult {
  void options;
  const [rootPath, setRootPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedPaths, setExpandedPaths] = useState<string[]>([]);
  const [branches, setBranches] = useState<Record<string, FileTreeBranchState>>({});
  const [highlightedPath, setHighlightedPath] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const expandedPathsRef = useRef<string[]>([]);
  const selectedPathRef = useRef("");
  const highlightTimerRef = useRef<number | null>(null);

  useEffect(() => {
    expandedPathsRef.current = expandedPaths;
  }, [expandedPaths]);

  useEffect(() => {
    selectedPathRef.current = selectedPath;
  }, [selectedPath]);

  const loadBranch = useCallback(async (currentRootPath: string, branchPath: string) => {
    setBranches((current) => ({
      ...current,
      [branchPath]: {
        entries: current[branchPath]?.entries || [],
        loading: true,
        loaded: current[branchPath]?.loaded || false,
        error: "",
      },
    }));

    try {
      const listing = await client.listFiles(botAlias, joinAbsoluteTreePath(currentRootPath, branchPath));
      const branchState = {
        entries: mapBranchEntries(branchPath, listing.entries),
        loading: false,
        loaded: true,
        error: "",
      };
      setBranches((current) => ({
        ...current,
        [branchPath]: branchState,
      }));
      return branchState;
    } catch (nextError) {
      setBranches((current) => ({
        ...current,
        [branchPath]: {
          entries: current[branchPath]?.entries || [],
          loading: false,
          loaded: false,
          error: getErrorMessage(nextError, "加载目录失败"),
        },
      }));
      throw nextError;
    }
  }, [botAlias, client]);

  const loadExpandedPathsForRoot = useCallback(async (currentRootPath: string, paths: string[]) => {
    const loadedBranches: Record<string, FileTreeBranchState> = {};
    for (const path of uniqueExpandedPaths(paths)) {
      try {
        loadedBranches[path] = await loadBranch(currentRootPath, path);
      } catch {
        // Branch state already captures the error.
      }
    }
    return loadedBranches;
  }, [loadBranch]);

  const refreshRoot = useCallback(async (options?: { preserveExpandedPaths?: boolean }) => {
    const preserveExpandedPaths = options?.preserveExpandedPaths === true;
    setLoading(true);
    setError("");
    try {
      const listing = await client.listFiles(botAlias);
      const nextRootPath = listing.workingDir;
      const nextExpandedPaths = preserveExpandedPaths ? expandedPathsRef.current : [];
      const normalizedExpandedPaths = uniqueExpandedPaths(nextExpandedPaths);
      const rootBranch = {
        entries: mapBranchEntries("", listing.entries),
        loading: false,
        loaded: true,
        error: "",
      };
      const nextBranches: Record<string, FileTreeBranchState> = {
        "": rootBranch,
      };

      setRootPath(nextRootPath);
      setExpandedPaths(normalizedExpandedPaths);
      setBranches(nextBranches);

      if (normalizedExpandedPaths.length > 0) {
        Object.assign(nextBranches, await loadExpandedPathsForRoot(nextRootPath, normalizedExpandedPaths));
      }

      if (selectedPathRef.current && !branchMapContainsPath(nextBranches, selectedPathRef.current)) {
        clearSelection();
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载文件树失败"));
      setBranches({});
      clearSelection();
    } finally {
      setLoading(false);
    }
  }, [botAlias, client, loadExpandedPathsForRoot]);

  useEffect(() => {
    void refreshRoot();
  }, [refreshRoot]);

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current !== null) {
        window.clearTimeout(highlightTimerRef.current);
      }
    };
  }, []);

  function selectPath(path: string) {
    const nextPath = path.trim();
    selectedPathRef.current = nextPath;
    setSelectedPath(nextPath);
  }

  function clearSelection() {
    selectedPathRef.current = "";
    setSelectedPath("");
  }

  function highlightPath(path: string) {
    setHighlightedPath(path);
    if (highlightTimerRef.current !== null) {
      window.clearTimeout(highlightTimerRef.current);
    }
    highlightTimerRef.current = window.setTimeout(() => {
      setHighlightedPath((current) => current === path ? "" : current);
      highlightTimerRef.current = null;
    }, WORKBENCH_HIGHLIGHT_DURATION_MS);
  }

  async function refreshBranch(branchPath: string) {
    if (!rootPath) {
      return;
    }
    if (!branchPath) {
      await refreshRoot({ preserveExpandedPaths: true });
      return;
    }
    await loadBranch(rootPath, branchPath);
  }

  async function restoreExpandedPaths(paths: string[]) {
    if (!rootPath) {
      return;
    }
    const normalizedPaths = uniqueExpandedPaths(paths);
    setExpandedPaths(normalizedPaths);
    await loadExpandedPathsForRoot(rootPath, normalizedPaths);
  }

  async function revealPath(path: string) {
    if (!rootPath) {
      return;
    }
    const result = await client.revealFileTreePath(botAlias, path);
    const nextBranches = Object.fromEntries(
      Object.entries(result.branches).map(([branchPath, entries]) => [
        branchPath,
        {
          entries: mapBranchEntries(branchPath, entries),
          loading: false,
          loaded: true,
          error: "",
        },
      ]),
    );
    const nextExpandedPaths = uniqueExpandedPaths([
      ...expandedPathsRef.current,
      ...result.expandedPaths,
      ...ancestorPathsForPath(result.highlightPath || path),
    ]);
    expandedPathsRef.current = nextExpandedPaths;
    setExpandedPaths(nextExpandedPaths);
    setBranches((current) => ({
      ...current,
      ...nextBranches,
    }));
    const nextSelectedPath = result.highlightPath || path;
    selectPath(nextSelectedPath);
    highlightPath(nextSelectedPath);
  }

  async function toggleDirectory(path: string) {
    const isExpanded = expandedPathsRef.current.includes(path);
    if (isExpanded) {
      setExpandedPaths((current) => current.filter((item) => item !== path));
      return;
    }

    setExpandedPaths((current) => uniqueExpandedPaths([...current, path]));
    if (!branches[path]?.loaded) {
      try {
        await loadBranch(rootPath, path);
      } catch {
        // Branch state already captures the error.
      }
    }
  }

  async function createDirectory(name: string, parentPath = "") {
    await client.createDirectory(
      botAlias,
      name,
      parentPath ? joinAbsoluteTreePath(rootPath, parentPath) : undefined,
    );
    await refreshBranch(parentPath);
    const nextPath = parentPath ? `${parentPath}/${name}` : name;
    selectPath(nextPath);
    highlightPath(nextPath);
  }

  async function createFile(filename: string, content = "", parentPath = "") {
    const result = await client.createTextFile(
      botAlias,
      filename,
      content,
      parentPath ? joinAbsoluteTreePath(rootPath, parentPath) : undefined,
    );
    await refreshBranch(parentPath);
    selectPath(result.path);
    highlightPath(result.path);
    return result;
  }

  async function renameFile(path: string, newName: string) {
    const result = await client.renamePath(botAlias, path, newName);
    await refreshBranch(parentTreePath(path));
    selectPath(result.path);
    highlightPath(result.path);
    return result;
  }

  async function copyFile(path: string) {
    const result = await client.copyPath(botAlias, path);
    await refreshBranch(parentTreePath(path));
    selectPath(result.path);
    highlightPath(result.path);
    return result;
  }

  async function moveFile(path: string, targetParentPath: string) {
    const result = await client.movePath(botAlias, path, targetParentPath);
    const sourceParentPath = parentTreePath(path);
    const targetExpandedPaths = uniqueExpandedPaths([...expandedPathsRef.current, ...ancestorPathsForPath(result.path)]);
    expandedPathsRef.current = targetExpandedPaths;
    setExpandedPaths(targetExpandedPaths);
    if (sourceParentPath !== targetParentPath) {
      await refreshBranch(sourceParentPath);
    }
    await refreshBranch(targetParentPath);
    selectPath(result.path);
    highlightPath(result.path);
    return result;
  }

  function resolveSelectionAfterDelete(path: string) {
    const parentPath = parentTreePath(path);
    const siblings = branchEntriesForPath(branches, parentPath);
    const index = siblings.findIndex((entry) => entry.path === path);
    if (index >= 0) {
      const nextSibling = siblings[index + 1] || siblings[index - 1];
      if (nextSibling) {
        return nextSibling.path;
      }
    }
    return parentPath;
  }

  async function deletePath(path: string) {
    const selectedBeforeDelete = selectedPathRef.current;
    const shouldMoveSelection = selectedBeforeDelete
      ? isSameOrDescendantPath(selectedBeforeDelete, path)
      : false;
    const nextSelectedPath = shouldMoveSelection ? resolveSelectionAfterDelete(path) : selectedBeforeDelete;

    await client.deletePath(botAlias, path);
    setExpandedPaths((current) => current.filter((item) => item !== path && !item.startsWith(`${path}/`)));
    setBranches((current) => Object.fromEntries(
      Object.entries(current).filter(([key]) => key !== path && !key.startsWith(`${path}/`)),
    ));
    if (shouldMoveSelection) {
      selectPath(nextSelectedPath);
    }
    await refreshBranch(parentTreePath(path));
  }

  async function downloadFile(path: string) {
    await client.downloadFile(botAlias, path);
  }

  return {
    rootPath,
    loading,
    error,
    rootEntries: branches[""]?.entries || [],
    branches,
    expandedPaths,
    highlightedPath,
    selectedPath,
    selectPath,
    clearSelection,
    isExpanded: (path: string) => expandedPaths.includes(path),
    toggleDirectory,
    refreshRoot,
    restoreExpandedPaths,
    revealPath,
    highlightPath,
    createDirectory,
    createFile,
    renameFile,
    copyFile,
    moveFile,
    deletePath,
    downloadFile,
  };
}
