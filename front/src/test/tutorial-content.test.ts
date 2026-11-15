import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { TUTORIAL_CHAPTERS, TUTORIAL_SHOTS, tutorialShotKey } from "../tutorial/tutorialContent";
import { CALLOUT_MARGIN, MAX_STAGE_ZOOM, hotspotFrameBox, placeCallout, stageTransform } from "../tutorial/tutorialMotion";

const assetRoot = path.resolve(process.cwd(), "public", "assets", "tutorial");
const FILE_BUDGET = 400 * 1024;
const TOTAL_BUDGET = 10 * 1024 * 1024;

const steps = TUTORIAL_CHAPTERS.flatMap((chapter) => chapter.steps.map((step) => ({ chapter, step })));

function assetFiles(dir: string): string[] {
  if (!fs.existsSync(dir)) {
    return [];
  }
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (
    entry.isDirectory() ? assetFiles(path.join(dir, entry.name)) : [path.join(dir, entry.name)]
  ));
}

describe("tutorial content", () => {
  it("keeps chapter and step ids unique and step fields within their limits", () => {
    const chapterIds = TUTORIAL_CHAPTERS.map((chapter) => chapter.id);
    expect(chapterIds).toEqual(["start", "chat", "layout", "files", "terminal", "git", "cluster", "remote", "gateways", "admin", "tips"]);
    for (const chapter of TUTORIAL_CHAPTERS) {
      const stepIds = chapter.steps.map((step) => step.id);
      expect(new Set(stepIds).size, `${chapter.id} step ids`).toBe(stepIds.length);
      // No placeholder chapters: each one has between three and seven steps.
      expect(stepIds.length, `${chapter.id} step count`).toBeGreaterThanOrEqual(3);
      expect(stepIds.length, `${chapter.id} step count`).toBeLessThanOrEqual(7);
    }
    for (const { chapter, step } of steps) {
      const label = `${chapter.id}/${step.id}`;
      expect((step.title.match(/\p{Script=Han}/gu) || []).length, `${label} title`).toBeLessThanOrEqual(14);
      expect(step.body.length, `${label} body`).toBeGreaterThanOrEqual(1);
      expect(step.body.length, `${label} body`).toBeLessThanOrEqual(3);
      expect(step.alt.trim(), `${label} alt`).not.toBe("");
      if (step.zoom !== undefined) {
        expect(step.zoom, `${label} zoom`).toBeGreaterThanOrEqual(1);
        expect(step.zoom, `${label} zoom`).toBeLessThanOrEqual(MAX_STAGE_ZOOM);
      }
    }
  });

  it("references only screenshots and hotspots that were generated, and ships no unused screenshot", () => {
    const referenced = new Set<string>();
    for (const { chapter, step } of steps) {
      const key = tutorialShotKey(chapter.id, step.shot);
      referenced.add(key);
      expect(fs.existsSync(path.join(assetRoot, chapter.id, `${step.shot}.webp`)), `${key}.webp on disk`).toBe(true);
      expect(TUTORIAL_SHOTS[key], `${key} in shots.generated.json`).toBeDefined();
      if (step.hotspot) {
        expect(TUTORIAL_SHOTS[key]?.hotspots[step.hotspot], `${key} hotspot ${step.hotspot}`).toBeDefined();
      }
    }
    const shipped = assetFiles(assetRoot).map((file) => (
      path.relative(assetRoot, file).split(path.sep).join("/").replace(/\.webp$/, "")
    ));
    expect(shipped.sort()).toEqual([...referenced].sort());
    expect(Object.keys(TUTORIAL_SHOTS).sort()).toEqual([...referenced].sort());
  });

  it("keeps the screenshots within the size budgets", () => {
    const sizes = assetFiles(assetRoot).map((file) => ({ file, size: fs.statSync(file).size }));
    for (const { file, size } of sizes) {
      expect(size, path.relative(assetRoot, file)).toBeLessThanOrEqual(FILE_BUDGET);
    }
    expect(sizes.reduce((total, item) => total + item.size, 0)).toBeLessThanOrEqual(TOTAL_BUDGET);
  });
});

describe("stageTransform", () => {
  it("never exposes an edge of the frame, even for hotspots in the four corners", () => {
    const corners = [
      { x: 0, y: 0, w: 4, h: 4 },
      { x: 96, y: 0, w: 4, h: 4 },
      { x: 0, y: 96, w: 4, h: 4 },
      { x: 96, y: 96, w: 4, h: 4 },
    ];
    for (const hotspot of corners) {
      for (const zoom of [1, 1.4, MAX_STAGE_ZOOM, 5]) {
        const { scale, x, y } = stageTransform(hotspot, zoom);
        expect(scale).toBeLessThanOrEqual(MAX_STAGE_ZOOM);
        // The canvas spans [offset, offset + 100 * scale] in percentages of the frame.
        for (const offset of [x, y]) {
          expect(offset).toBeLessThanOrEqual(0);
          expect(offset + 100 * scale).toBeGreaterThanOrEqual(100);
        }
      }
    }
    expect(stageTransform({ x: 45, y: 45, w: 10, h: 10 }, 1.5)).toEqual({ scale: 1.5, x: -25, y: -25 });
    expect(stageTransform(undefined, 1.8)).toEqual({ scale: 1, x: 0, y: 0 });
  });
});

describe("placeCallout", () => {
  const frame = { width: 775, height: 484 };
  const size = { width: 300, height: 150 };
  const insideFrame = ({ left, top }: { left: number; top: number }) => (
    left >= CALLOUT_MARGIN
    && top >= CALLOUT_MARGIN
    && left + size.width <= frame.width - CALLOUT_MARGIN
    && top + size.height <= frame.height - CALLOUT_MARGIN
  );
  const overlaps = (placement: { left: number; top: number }, target: { left: number; top: number; width: number; height: number }) => (
    placement.left < target.left + target.width
    && target.left < placement.left + size.width
    && placement.top < target.top + target.height
    && target.top < placement.top + size.height
  );

  it("keeps the callout inside the frame and off small hotspots in the corners and the centre", () => {
    const targets = [
      { left: 0, top: 0, width: 40, height: 30 },
      { left: 735, top: 0, width: 40, height: 30 },
      { left: 0, top: 454, width: 40, height: 30 },
      { left: 735, top: 454, width: 40, height: 30 },
      { left: 367, top: 227, width: 40, height: 30 },
    ];
    for (const target of targets) {
      const placement = placeCallout(target, frame, size);
      expect(insideFrame(placement), JSON.stringify(target)).toBe(true);
      expect(overlaps(placement, target), JSON.stringify(target)).toBe(false);
    }
  });

  it("prefers below, then above, then the sides, and falls back to the corner without a hotspot", () => {
    expect(placeCallout({ left: 20, top: 10, width: 120, height: 30 }, frame, size).side).toBe("below");
    expect(placeCallout({ left: 500, top: 400, width: 200, height: 60 }, frame, size).side).toBe("above");
    expect(placeCallout({ left: 0, top: 0, width: 180, height: 484 }, frame, size).side).toBe("right");
    expect(placeCallout(null, frame, size)).toEqual({ side: "corner", left: CALLOUT_MARGIN, top: 484 - 150 - CALLOUT_MARGIN });
    expect(insideFrame(placeCallout({ left: -40, top: -30, width: 900, height: 600 }, frame, size))).toBe(true);
  });

  it("maps the hotspot through the stage transform into frame pixels", () => {
    const hotspot = { x: 45, y: 45, w: 10, h: 10 };
    expect(hotspotFrameBox(hotspot, stageTransform(hotspot, 1.5), { width: 800, height: 500 }))
      .toEqual({ left: 340, top: 212.5, width: 120, height: 75 });
  });
});
