import { useCallback, useEffect, useState } from "react";
import type { FileCreateResult, FileRenameResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

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
  isExpanded: (path: string) => boolean;
  toggleDirectory: (path: string) => Promise<void>;
  refreshRoot: () => Promise<void>;
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

export function useFileTree(botAlias: string, client: WebBotClient): UseFileTreeResult {
  const [rootPath, setRootPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedPaths, setExpandedPaths] = useState<string[]>([]);
  const [branches, setBranches] = useState<Record<string, FileTreeBranchState>>({});

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

  const refreshRoot = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const nextRootPath = await client.getCurrentPath(botAlias);
      await client.changeDirectory(botAlias, nextRootPath);
      const listing = await client.listFiles(botAlias, nextRootPath);
      setRootPath(nextRootPath);
      setExpandedPaths([]);
      setBranches({
        "": {
          entries: mapBranchEntries("", listing.entries),
          loading: false,
          loaded: true,
          error: "",
        },
      });
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载文件树失败"));
      setBranches({});
    } finally {
      setLoading(false);
    }
  }, [botAlias, client]);

  useEffect(() => {
    void refreshRoot();
  }, [refreshRoot]);

  async function refreshBranch(branchPath: string) {
    if (!rootPath) {
      return;
    }
    if (!branchPath) {
      await refreshRoot();
      return;
    }
    await loadBranch(rootPath, branchPath);
  }

  async function toggleDirectory(path: string) {
    const isExpanded = expandedPaths.includes(path);
    if (isExpanded) {
      setExpandedPaths((current) => current.filter((item) => item !== path));
      return;
    }

    setExpandedPaths((current) => [...current, path]);
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
  }

  async function createFile(filename: string, content = "", parentPath = "") {
    const result = await client.createTextFile(
      botAlias,
      filename,
      content,
      parentPath ? joinAbsoluteTreePath(rootPath, parentPath) : undefined,
    );
    await refreshBranch(parentPath);
    return result;
  }

  async function renameFile(path: string, newName: string) {
    const result = await client.renamePath(botAlias, path, newName);
    await refreshBranch(parentTreePath(path));
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
    isExpanded: (path: string) => expandedPaths.includes(path),
    toggleDirectory,
    refreshRoot,
    createDirectory,
    createFile,
    renameFile,
    deletePath,
    downloadFile,
  };
}
