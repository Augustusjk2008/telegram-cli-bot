import { FileEntry } from "../services/types";
import { DEMO_MAIN_WORKDIR, DEMO_TEAM_WORKDIR } from "./demoEnvironment";

function entry(name: string, isDir: boolean, size?: number): FileEntry {
  return {
    name,
    isDir,
    ...(typeof size === "number" ? { size } : {}),
    updatedAt: "2026-04-22T10:00:00Z",
  };
}

export const mockFiles: Record<string, Record<string, FileEntry[]>> = {
  main: {
    [DEMO_MAIN_WORKDIR]: [
      entry("docs", true),
      entry("reports", true),
      entry("src", true),
      entry("waves", true),
      entry("README.md", false, 640),
      entry("package.json", false, 1024),
    ],
    [`${DEMO_MAIN_WORKDIR}/docs`]: [
      entry("architecture.md", false, 1536),
      entry("plugin-plan.md", false, 2048),
      entry("roadmap.docx", false, 40960),
      entry("roadmap.pdf", false, 24576),
      entry("roadmap.xlsx", false, 32768),
      entry("sample.zip", false, 8192),
    ],
    [`${DEMO_MAIN_WORKDIR}/src`]: [
      entry("index.ts", false, 512),
      entry("server.ts", false, 896),
    ],
    [`${DEMO_MAIN_WORKDIR}/reports`]: [
      entry("timing.rpt", false, 768),
      entry("design.hier", false, 512),
      entry("firmware.bin", false, 4096),
    ],
    [`${DEMO_MAIN_WORKDIR}/waves`]: [
      entry("simple_counter.vcd", false, 1024),
    ],
  },
  team2: {
    [DEMO_TEAM_WORKDIR]: [
      entry("docs", true),
      entry("plans.md", false, 768),
    ],
    [`${DEMO_TEAM_WORKDIR}/docs`]: [
      entry("summary.md", false, 512),
    ],
  },
};
