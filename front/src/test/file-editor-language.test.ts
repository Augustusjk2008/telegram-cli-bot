import { expect, test } from "vitest";
import { loadFileEditorExtensions } from "../utils/fileEditorLanguage";

test("loads Verilog and SystemVerilog editor extensions", async () => {
  await expect(loadFileEditorExtensions("counter.v")).resolves.not.toHaveLength(0);
  await expect(loadFileEditorExtensions("defs.sv")).resolves.not.toHaveLength(0);
  await expect(loadFileEditorExtensions("pkg.svh")).resolves.not.toHaveLength(0);
});
