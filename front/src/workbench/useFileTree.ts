import { useCallback, useEffect, useRef, useState } from "react";
import type { FileCopyResult, FileCreateResult, FileDownloadProgress, FileMoveResult, FileRenameResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import { WORKBENCH_EXPANDED_PATH_RESTORE_LIMIT, WORKBENCH_HIGHLIGHT_DURATION_MS } from "./workbenchTypes";

export type FileTreeNode = {
  path: string;
  name: string;
  isDir: boolean;
  childCount?: number;
  size?: number;
  updatedAt?: string;
};

type FileTreeBranchState = {
  entries: FileTreeNode[];
  loading: boolean;
  loaded: boolean;
  error: string;
};

type BranchLoadOptions = {
  force?: boolean;
  generation?: number;
};

type InFlightBranchLoad = {
  generation: number;
  promise: Promise<FileTreeBranchState>;
};

export type FileTreeDownloadProgress = FileDownloadProgress & {
  path: string;
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
  downloadProgress: FileTreeDownloadProgress | null;
  selectPath: (path: string) => void;
  clearSelection: () => void;
  isExpanded: (path: string) => boolean;
  toggleDirectory: (path: string) => Promise<void>;
  refreshRoot: (options?: { preserveExpandedPaths?: boolean; rootPath?: string }) => Promise<void>;
  refreshTreeAndRoot: (options?: { preserveExpandedPaths?: boolean; rootPath?: string }) => Promise<string>;
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

function branchMapConfirmsMissingPath(
  branchMap: Record<string, FileTreeBranchState>,
  path: string,
) {
  if (!path) {
    return false;
  }
  const parentPath = parentTreePath(path);
  const parentBranch = branchMap[parentPath];
  if (!parentBranch?.loaded) {
    return false;
  }
  return !parentBranch.entries.some((entry) => entry.path === path);
}

function mapBranchEntries(
  parentPath: string,
  entries: Array<{ name: string; isDir: boolean; childCount?: number; size?: number; updatedAt?: string }>,
) {
  return entries.map((entry) => ({
    path: joinTreePath(parentPath, entry.name),
    name: entry.name,
    isDir: entry.isDir,
    childCount: entry.childCount,
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
  const [downloadProgress, setDownloadProgress] = useState<FileTreeDownloadProgress | null>(null);
  const expandedPathsRef = useRef<string[]>([]);
  const branchesRef = useRef<Record<string, FileTreeBranchState>>({});
  const selectedPathRef = useRef("");
  const highlightTimerRef = useRef<number | null>(null);
  const loadGenerationRef = useRef(0);
  const branchRequestSeqRef = useRef<Map<string, number>>(new Map());
  const inFlightBranchLoadsRef = useRef<Map<string, InFlightBranchLoad>>(new Map());
  const backgroundRestoreIdRef = useRef(0);

  useEffect(() => {
    expandedPathsRef.current = expandedPaths;
  }, [expandedPaths]);

  useEffect(() => {
    branchesRef.current = branches;
  }, [branches]);

  useEffect(() => {
    selectedPathRef.current = selectedPath;
  }, [selectedPath]);

  function setExpandedPathsSynced(nextPaths: string[]) {
    expandedPathsRef.current = nextPaths;
    setExpandedPaths(nextPaths);
  }

  function updateExpandedPathsSynced(updater: (current: string[]) => string[]) {
    const nextPaths = updater(expandedPathsRef.current);
    setExpandedPathsSynced(nextPaths);
    return nextPaths;
  }

  function setBranchesSynced(
    nextBranches: Record<string, FileTreeBranchState> | ((current: Record<string, FileTreeBranchState>) => Record<string, FileTreeBranchState>),
  ) {
    const resolvedBranches = typeof nextBranches === "function" ? nextBranches(branchesRef.current) : nextBranches;
    branchesRef.current = resolvedBranches;
    setBranches(resolvedBranches);
    return resolvedBranches;
  }

  function clearSelectionIfConfirmedMissing(branchMap: Record<string, FileTreeBranchState>, path: string) {
    if (branchMapConfirmsMissingPath(branchMap, path)) {
      clearSelection();
    }
  }

  function branchLoadKey(currentRootPath: string, branchPath: string) {
    return `${currentRootPath}\0${branchPath}`;
  }

  const loadBranch = useCallback(async (currentRootPath: string, branchPath: string, options?: BranchLoadOptions) => {
    const generation = options?.generation ?? loadGenerationRef.current;
    const key = branchLoadKey(currentRootPath, branchPath);
    const force = options?.force === true;
    const currentBranch = branchesRef.current[branchPath];
    if (!force && currentBranch?.loaded) {
      return currentBranch;
    }

    const inFlight = inFlightBranchLoadsRef.current.get(key);
    if (!force && inFlight?.generation === generation) {
      return inFlight.promise;
    }

    const previousSeq = branchRequestSeqRef.current.get(key) ?? 0;
    const requestSeq = force ? previousSeq + 1 : previousSeq;
    if (force) {
      branchRequestSeqRef.current.set(key, requestSeq);
    }

    if (loadGenerationRef.current === generation) {
      setBranchesSynced((current) => ({
        ...current,
        [branchPath]: {
          entries: current[branchPath]?.entries || [],
          loading: true,
          loaded: current[branchPath]?.loaded || false,
          error: "",
        },
      }));
    }

    const promise = (async () => {
      try {
        const listing = await client.listFiles(
          botAlias,
          joinAbsoluteTreePath(currentRootPath, branchPath),
          { includeChildCounts: true },
        );
        const branchState = {
          entries: mapBranchEntries(branchPath, listing.entries),
          loading: false,
          loaded: true,
          error: "",
        };
        if (
          loadGenerationRef.current === generation
          && (branchRequestSeqRef.current.get(key) ?? 0) === requestSeq
        ) {
          const nextBranches = setBranchesSynced((current) => ({
            ...current,
            [branchPath]: branchState,
          }));
          clearSelectionIfConfirmedMissing(nextBranches, selectedPathRef.current);
        }
        return branchState;
      } catch (nextError) {
        if (
          loadGenerationRef.current === generation
          && (branchRequestSeqRef.current.get(key) ?? 0) === requestSeq
        ) {
          setBranchesSynced((current) => ({
            ...current,
            [branchPath]: {
              entries: current[branchPath]?.entries || [],
              loading: false,
              loaded: false,
              error: getErrorMessage(nextError, "加载目录失败"),
            },
          }));
        }
        throw nextError;
      } finally {
        const currentInFlight = inFlightBranchLoadsRef.current.get(key);
        if (currentInFlight?.promise === promise) {
          inFlightBranchLoadsRef.current.delete(key);
        }
      }
    })();

    inFlightBranchLoadsRef.current.set(key, { generation, promise });
    return promise;
  }, [botAlias, client]);

  const startBackgroundRestoreExpandedPaths = useCallback((currentRootPath: string, paths: string[], generation: number) => {
    const normalizedPaths = uniqueExpandedPaths(paths);
    const restoreId = backgroundRestoreIdRef.current + 1;
    backgroundRestoreIdRef.current = restoreId;
    setExpandedPathsSynced(normalizedPaths);

    if (normalizedPaths.length === 0) {
      return;
    }

    setBranchesSynced((current) => {
      if (loadGenerationRef.current !== generation) {
        return current;
      }
      const nextBranches = { ...current };
      for (const path of normalizedPaths) {
        const existing = nextBranches[path];
        if (existing?.loaded) {
          continue;
        }
        nextBranches[path] = {
          entries: existing?.entries || [],
          loading: true,
          loaded: false,
          error: "",
        };
      }
      return nextBranches;
    });

    let nextIndex = 0;
    const runWorker = async () => {
      while (nextIndex < normalizedPaths.length) {
        const path = normalizedPaths[nextIndex];
        nextIndex += 1;
        if (loadGenerationRef.current !== generation || backgroundRestoreIdRef.current !== restoreId) {
          return;
        }
        if (!expandedPathsRef.current.includes(path)) {
          continue;
        }
        if (branchesRef.current[path]?.loaded) {
          continue;
        }
        const key = branchLoadKey(currentRootPath, path);
        if (inFlightBranchLoadsRef.current.get(key)?.generation === generation) {
          continue;
        }
        try {
          await loadBranch(currentRootPath, path, { generation });
        } catch {
          // Branch state already captures the error.
        }
      }
    };

    void Promise.all([runWorker(), runWorker()]);
  }, [loadBranch]);

  const refreshRoot = useCallback(async (options?: { preserveExpandedPaths?: boolean; rootPath?: string }) => {
    const generation = loadGenerationRef.current + 1;
    loadGenerationRef.current = generation;
    backgroundRestoreIdRef.current += 1;
    inFlightBranchLoadsRef.current.clear();
    const preserveExpandedPaths = options?.preserveExpandedPaths === true;
    setLoading(true);
    setError("");
    try {
      const listing = await client.listFiles(botAlias, options?.rootPath, { includeChildCounts: true });
      if (loadGenerationRef.current !== generation) {
        return;
      }
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
      setBranchesSynced(nextBranches);
      setExpandedPathsSynced([]);

      if (normalizedExpandedPaths.length > 0) {
        startBackgroundRestoreExpandedPaths(nextRootPath, normalizedExpandedPaths, generation);
      }

      clearSelectionIfConfirmedMissing(nextBranches, selectedPathRef.current);
    } catch (nextError) {
      if (loadGenerationRef.current === generation) {
        setError(getErrorMessage(nextError, "加载文件树失败"));
        setBranchesSynced({});
        clearSelection();
      }
    } finally {
      if (loadGenerationRef.current === generation) {
        setLoading(false);
      }
    }
  }, [botAlias, client, startBackgroundRestoreExpandedPaths]);

  const refreshTreeAndRoot = useCallback(async (options?: { preserveExpandedPaths?: boolean; rootPath?: string }) => {
    const generation = loadGenerationRef.current + 1;
    loadGenerationRef.current = generation;
    backgroundRestoreIdRef.current += 1;
    inFlightBranchLoadsRef.current.clear();
    const preserveExpandedPaths = options?.preserveExpandedPaths === true;
    setLoading(true);
    setError("");
    try {
      const listing = await client.listFiles(botAlias, options?.rootPath, { includeChildCounts: true });
      if (loadGenerationRef.current !== generation) {
        return listing.workingDir;
      }
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
      setBranchesSynced(nextBranches);
      setExpandedPathsSynced([]);

      if (normalizedExpandedPaths.length > 0) {
        startBackgroundRestoreExpandedPaths(nextRootPath, normalizedExpandedPaths, generation);
      }

      clearSelectionIfConfirmedMissing(nextBranches, selectedPathRef.current);
      return nextRootPath;
    } catch (nextError) {
      if (loadGenerationRef.current === generation) {
        setError(getErrorMessage(nextError, "加载文件树失败"));
        setBranchesSynced({});
        clearSelection();
      }
      throw nextError;
    } finally {
      if (loadGenerationRef.current === generation) {
        setLoading(false);
      }
    }
  }, [botAlias, client, startBackgroundRestoreExpandedPaths]);

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
    await loadBranch(rootPath, branchPath, { force: true });
  }

  async function restoreExpandedPaths(paths: string[]) {
    if (!rootPath) {
      return;
    }
    startBackgroundRestoreExpandedPaths(rootPath, paths, loadGenerationRef.current);
  }

  async function revealPath(path: string) {
    if (!rootPath) {
      return;
    }
    const generation = loadGenerationRef.current;
    const result = await client.revealFileTreePath(botAlias, path);
    if (loadGenerationRef.current !== generation) {
      return;
    }
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
    setExpandedPathsSynced(nextExpandedPaths);
    setBranchesSynced((current) => ({
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
      updateExpandedPathsSynced((current) => current.filter((item) => item !== path));
      return;
    }

    updateExpandedPathsSynced((current) => uniqueExpandedPaths([...current, path]));
    if (!branchesRef.current[path]?.loaded) {
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
      joinAbsoluteTreePath(rootPath, parentPath),
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
      joinAbsoluteTreePath(rootPath, parentPath),
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
    setExpandedPathsSynced(targetExpandedPaths);
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
    const siblings = branchEntriesForPath(branchesRef.current, parentPath);
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
    updateExpandedPathsSynced((current) => current.filter((item) => item !== path && !item.startsWith(`${path}/`)));
    setBranchesSynced((current) => Object.fromEntries(
      Object.entries(current).filter(([key]) => key !== path && !key.startsWith(`${path}/`)),
    ));
    if (shouldMoveSelection) {
      selectPath(nextSelectedPath);
    }
    await refreshBranch(parentTreePath(path));
  }

  async function downloadFile(path: string) {
    setDownloadProgress({ path, downloadedBytes: 0 });
    try {
      await client.downloadFile(botAlias, path, (progress) => {
        setDownloadProgress({ path, ...progress });
      });
    } catch (nextError) {
      setError(getErrorMessage(nextError, "下载文件失败"));
      throw nextError;
    } finally {
      setDownloadProgress(null);
    }
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
    downloadProgress,
    selectPath,
    clearSelection,
    isExpanded: (path: string) => expandedPaths.includes(path),
    toggleDirectory,
    refreshRoot,
    refreshTreeAndRoot,
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
