import type { Capability, SessionState } from "../services/types";

export function hasCapability(session: SessionState | null, capability: Capability) {
  return Boolean(session && session.capabilities.includes(capability));
}

export function isGuest(session: SessionState | null) {
  return session?.role === "guest";
}
