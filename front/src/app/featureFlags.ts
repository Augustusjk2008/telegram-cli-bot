type FeatureFlagEnvironment = Record<string, unknown>;

export function readFeatureFlag(
  environment: FeatureFlagEnvironment,
  key: string,
  fallback = true,
) {
  const value = environment[key];
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  return !["0", "false", "no", "off"].includes(String(value).trim().toLowerCase());
}

const environment = import.meta.env as FeatureFlagEnvironment;

export const FRONTEND_FEATURE_FLAGS = {
  chatFrameBatching: readFeatureFlag(environment, "VITE_CHAT_FRAME_BATCHING_ENABLED"),
  dynamicChatVirtualization: readFeatureFlag(environment, "VITE_DYNAMIC_CHAT_VIRTUALIZATION_ENABLED"),
  historyRevisionSync: readFeatureFlag(environment, "VITE_HISTORY_REVISION_SYNC_ENABLED"),
  routeLazyLoading: readFeatureFlag(environment, "VITE_ROUTE_LAZY_LOADING_ENABLED"),
} as const;
