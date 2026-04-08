import { FileEntry } from "../services/types";

export const mockFiles: Record<string, Record<string, FileEntry[]>> = {
  main: {
    "/": [
      { name: "src", isDir: true, updatedAt: "2023-10-01T10:00:00Z" },
      { name: "package.json", isDir: false, size: 1024, updatedAt: "2023-10-01T10:00:00Z" },
    ],
    "/src": [
      { name: "index.ts", isDir: false, size: 512, updatedAt: "2023-10-01T10:00:00Z" },
    ]
  }
};
