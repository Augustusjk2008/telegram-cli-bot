type MotionTarget = Record<string, string | number>;

export type PremiumMotionPreset = {
  initial: MotionTarget | false;
  animate: MotionTarget;
  exit?: MotionTarget;
  transition: {
    duration: number;
    delay?: number;
    ease?: [number, number, number, number];
  };
};

export const premiumMotionDurations = {
  quick: 0.12,
  standard: 0.16,
  calm: 0.2,
} as const;

export const premiumMotionEase: [number, number, number, number] = [0.2, 0, 0, 1];

export const premiumMotion = {
  shell: {
    initial: { opacity: 0.98 },
    animate: { opacity: 1 },
    transition: { duration: premiumMotionDurations.quick, ease: premiumMotionEase },
  },
  paletteBackdrop: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: premiumMotionDurations.quick, ease: premiumMotionEase },
  },
  palettePanel: {
    initial: { opacity: 0, y: -8, scale: 0.985 },
    animate: { opacity: 1, y: 0, scale: 1 },
    exit: { opacity: 0, y: -6, scale: 0.99 },
    transition: { duration: premiumMotionDurations.standard, ease: premiumMotionEase },
  },
  messageRow: {
    initial: { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: premiumMotionDurations.standard, ease: premiumMotionEase },
  },
  tracePanel: {
    initial: { opacity: 0, height: 0 },
    animate: { opacity: 1, height: "auto" },
    exit: { opacity: 0, height: 0 },
    transition: { duration: premiumMotionDurations.calm, ease: premiumMotionEase },
  },
} satisfies Record<string, PremiumMotionPreset>;

export const delightMotionDurations = {
  snap: 0.18,
  pop: 0.24,
  expressive: 0.32,
} as const;

export const delightMotion = {
  paletteItem: {
    initial: { opacity: 0, y: 5, scale: 0.992 },
    animate: { opacity: 1, y: 0, scale: 1 },
    exit: { opacity: 0, y: 3, scale: 0.996 },
    transition: { duration: delightMotionDurations.snap, ease: premiumMotionEase },
  },
  messagePop: {
    initial: { opacity: 0, y: 8, scale: 0.99 },
    animate: { opacity: 1, y: 0, scale: 1 },
    transition: { duration: delightMotionDurations.pop, ease: premiumMotionEase },
  },
  traceItem: {
    initial: { opacity: 0, y: 5, scale: 0.992 },
    animate: { opacity: 1, y: 0, scale: 1 },
    exit: { opacity: 0, y: 3, scale: 0.996 },
    transition: { duration: delightMotionDurations.snap, ease: premiumMotionEase },
  },
} satisfies Record<string, PremiumMotionPreset>;

export const delightMotionStagger = {
  itemDelaySeconds: 0.02,
  maxAnimatedItems: 12,
} as const;

export function resolveMotionProps(preset: PremiumMotionPreset, reduceMotion: boolean | null) {
  if (reduceMotion) {
    return {
      initial: false,
      animate: preset.animate,
      exit: preset.exit,
      transition: { duration: 0 },
    };
  }
  return preset;
}
