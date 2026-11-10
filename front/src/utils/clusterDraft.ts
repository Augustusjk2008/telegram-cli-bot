import type { BotClusterConfig, ClusterModelTier } from "../services/types";

const TIERS: ClusterModelTier[] = ["low", "medium", "high", "professional"];

/** Compares the fields edited through a cluster draft; `enabled` and the timeout text are tracked separately. */
export function clusterDraftEquals(left: BotClusterConfig, right: BotClusterConfig) {
  return left.writePolicy === right.writePolicy
    && left.maxParallelAgents === right.maxParallelAgents
    && TIERS.every((tier) => {
      const a = left.tierConfigs?.[tier];
      const b = right.tierConfigs?.[tier];
      return left.modelTiers[tier] === right.modelTiers[tier]
        && left.reasoningEfforts[tier] === right.reasoningEfforts[tier]
        && (a?.cliType || "") === (b?.cliType || "")
        && String(a?.cliPath || "").trim() === String(b?.cliPath || "").trim()
        && (a?.provider || "") === (b?.provider || "")
        && (a?.model || "") === (b?.model || "")
        && (a?.reasoningEffort || "") === (b?.reasoningEffort || "");
    });
}
