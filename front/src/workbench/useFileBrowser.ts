import { useEffect, useState } from "react";
import type { FileCreateResult, FileEntry, FileRenameResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
};

export type UseFileBrowserResult = {
  currentPath: string;
  files: FileEntry[];
  isVirtualRoot: boolean;
  loading: boolean;
  error: string;
  setError: (message: string) => void;
  loadListing: () => Promise<void>;
  goToDirectory: (name: string) => Promise<void>;
  goBack: () => Promise<void>;
  goHome: () => Promise<void>;
  createDirectory: (name: string) => Promise<void>;
  deleteEntry: (entry: FileEntry) => Promise<boolean>;
  downloadEntry: (entry: FileEntry) => Promise<void>;
  createFile: (filename: string, content?: string) => Promise<FileCreateResult>;
  renameFile: (path: string, newName: string) => Promise<FileRenameResult>;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useFileBrowser({ botAlias, client }: Props): UseFileBrowserResult {
  const [currentPath, setCurrentPath] = useState("/");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [isVirtualRoot, setIsVirtualRoot] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadListing() {
    setLoading(true);
    setError("");
    try {
      const listing = await client.listFiles(botAlias);
      setCurrentPath(listing.workingDir);
      setFiles(listing.entries);
      setIsVirtualRoot(Boolean(listing.isVirtualRoot));
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载目录失败"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadListing();
  }, [botAlias, client]);

  async function goToDirectory(name: string) {
    setError("");
    try {
      await client.changeDirectory(botAlias, name);
      await loadListing();
    } catch (nextError) {
      const message = getErrorMessage(nextError, "切换目录失败");
      setError(message);
      throw nextError;
    }
  }

  async function goBack() {
    setError("");
    try {
      await client.changeDirectory(botAlias, "..");
      await loadListing();
    } catch (nextError) {
      const message = getErrorMessage(nextError, "返回上级目录失败");
      setError(message);
      throw nextError;
    }
  }

  async function goHome() {
    setError("");
    try {
      const workingDir = await client.getCurrentPath(botAlias);
      await client.changeDirectory(botAlias, workingDir);
      await loadListing();
    } catch (nextError) {
      const message = getErrorMessage(nextError, "返回工作目录失败");
      setError(message);
      throw nextError;
    }
  }

  async function createDirectory(name: string) {
    setError("");
    try {
      await client.createDirectory(botAlias, name);
      await loadListing();
    } catch (nextError) {
      const message = getErrorMessage(nextError, "新建文件夹失败");
      setError(message);
      throw nextError;
    }
  }

  async function deleteEntry(entry: FileEntry) {
    setError("");
    try {
      await client.deletePath(botAlias, entry.name);
      await loadListing();
      return true;
    } catch (nextError) {
      const message = getErrorMessage(nextError, entry.isDir ? "删除文件夹失败" : "删除文件失败");
      setError(message);
      throw nextError;
    }
  }

  async function downloadEntry(entry: FileEntry) {
    setError("");
    try {
      await client.downloadFile(botAlias, entry.name);
    } catch (nextError) {
      const message = getErrorMessage(nextError, "下载文件失败");
      setError(message);
      throw nextError;
    }
  }

  async function createFile(filename: string, content = "") {
    setError("");
    try {
      const result = await client.createTextFile(botAlias, filename, content);
      await loadListing();
      return result;
    } catch (nextError) {
      const message = getErrorMessage(nextError, "新建文件失败");
      setError(message);
      throw nextError;
    }
  }

  async function renameFile(path: string, newName: string) {
    setError("");
    try {
      const result = await client.renamePath(botAlias, path, newName);
      await loadListing();
      return result;
    } catch (nextError) {
      const message = getErrorMessage(nextError, "重命名失败");
      setError(message);
      throw nextError;
    }
  }

  return {
    currentPath,
    files,
    isVirtualRoot,
    loading,
    error,
    setError,
    loadListing,
    goToDirectory,
    goBack,
    goHome,
    createDirectory,
    deleteEntry,
    downloadEntry,
    createFile,
    renameFile,
  };
}
