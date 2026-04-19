import { useCallback, useEffect, useRef, useState } from "react";
import type { FileCreateResult, FileRenameResult } from "../services/types";
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
  isExpanded: (path: string) => boolean;
  toggleDirectory: (path: string) => Promise<void>;
  refreshRoot: (options?: { preserveExpandedPaths?: boolean }) => Promise<void>;
  restoreExpandedPaths: (paths: string[]) => Promise<void>;
  revealPath: (path: string) => Promise<void>;
  highlightPath: (path: string) => void;
  createDirectory: (name: string, parentPath?: string) => Promise<void>;
  createFile: (filename: string, content?: string, parentPath?: string) => Promise<FileCreateResult>;
  renameFile: (path: string, newName: string) => Promise<FileRenameResult>;
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

export function useFileTree(botAlias: string, client: WebBotClient): UseFileTreeResult {
  const [rootPath, setRootPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedPaths, setExpandedPaths] = useState<string[]>([]);
  const [branches, setBranches] = useState<Record<string, FileTreeBranchState>>({});
  const [highlightedPath, setHighlightedPath] = useState("");
  const expandedPathsRef = useRef<string[]>([]);
  const highlightTimerRef = useRef<number | null>(null);

  useEffect(() => {
    expandedPathsRef.current = expandedPaths;
  }, [expandedPaths]);

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
      setBranches((current) => ({
        ...current,
        [branchPath]: {
          entries: mapBranchEntries(branchPath, listing.entries),
          loading: false,
          loaded: true,
          error: "",
        },
      }));
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
    for (const path of uniqueExpandedPaths(paths)) {
      try {
        await loadBranch(currentRootPath, path);
      } catch {
        // Branch state already captures the error.
      }
    }
  }, [loadBranch]);

  const refreshRoot = useCallback(async (options?: { preserveExpandedPaths?: boolean }) => {
    const preserveExpandedPaths = options?.preserveExpandedPaths === true;
    setLoading(true);
    setError("");
    try {
      const nextRootPath = await client.getCurrentPath(botAlias);
      await client.changeDirectory(botAlias, nextRootPath);
      const listing = await client.listFiles(botAlias, nextRootPath);
      const nextExpandedPaths = preserveExpandedPaths ? expandedPathsRef.current : [];
      const normalizedExpandedPaths = uniqueExpandedPaths(nextExpandedPaths);

      setRootPath(nextRootPath);
      setExpandedPaths(normalizedExpandedPaths);
      setBranches({
        "": {
          entries: mapBranchEntries("", listing.entries),
          loading: false,
          loaded: true,
          error: "",
        },
      });

      if (normalizedExpandedPaths.length > 0) {
        await loadExpandedPathsForRoot(nextRootPath, normalizedExpandedPaths);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载文件树失败"));
      setBranches({});
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
    const nextExpandedPaths = uniqueExpandedPaths([...expandedPathsRef.current, ...ancestorPathsForPath(path)]);
    setExpandedPaths(nextExpandedPaths);
    await loadExpandedPathsForRoot(rootPath, nextExpandedPaths);
    highlightPath(path);
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
    highlightPath(parentPath ? `${parentPath}/${name}` : name);
  }

  async function createFile(filename: string, content = "", parentPath = "") {
    const result = await client.createTextFile(
      botAlias,
      filename,
      content,
      parentPath ? joinAbsoluteTreePath(rootPath, parentPath) : undefined,
    );
    await refreshBranch(parentPath);
    highlightPath(result.path);
    return result;
  }

  async function renameFile(path: string, newName: string) {
    const result = await client.renamePath(botAlias, path, newName);
    await refreshBranch(parentTreePath(path));
    highlightPath(result.path);
    return result;
  }

  async function deletePath(path: string) {
    await client.deletePath(botAlias, path);
    setExpandedPaths((current) => current.filter((item) => item !== path && !item.startsWith(`${path}/`)));
    setBranches((current) => Object.fromEntries(
      Object.entries(current).filter(([key]) => key !== path && !key.startsWith(`${path}/`)),
    ));
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
    isExpanded: (path: string) => expandedPaths.includes(path),
    toggleDirectory,
    refreshRoot,
    restoreExpandedPaths,
    revealPath,
    highlightPath,
    createDirectory,
    createFile,
    renameFile,
    deletePath,
    downloadFile,
  };
}
