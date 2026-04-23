export function getDenseSegmentLayout(trackHeight: number) {
  const bandTop = Math.max(18, trackHeight * 0.28);
  const bandBottom = Math.min(trackHeight - 4, Math.max(bandTop + 8, trackHeight * 0.72));
  return {
    bandTop,
    bandBottom,
    labelY: Math.max(11, bandTop - 4),
    middleY: (bandTop + bandBottom) / 2,
  };
}
