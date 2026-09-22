import fs from "node:fs";
import path from "node:path";
import type { Plugin } from "vite";

// PDF.js fetches these resources by filename from its worker, including CJK maps.
export function pdfjsAssetsPlugin(frontRoot: string): Plugin {
  return {
    name: "pdfjs-assets",
    apply: "build",
    generateBundle() {
      for (const directory of ["cmaps", "standard_fonts", "wasm", "iccs"]) {
        const root = path.join(frontRoot, "node_modules/pdfjs-dist", directory);
        for (const filename of fs.readdirSync(root)) {
          this.emitFile({
            type: "asset",
            fileName: `assets/pdfjs/${directory}/${filename}`,
            source: fs.readFileSync(path.join(root, filename)),
          });
        }
      }
    },
  };
}
