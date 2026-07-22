import { useCallback, useEffect, useRef, useState } from "react";

export const CODE_NAVIGATION_HISTORY_LIMIT = 100;

export type CodeNavigationHistoryLocation = {
  path: string;
  line: number;
  column: number;
};

type HistoryState = {
  backStack: CodeNavigationHistoryLocation[];
  forwardStack: CodeNavigationHistoryLocation[];
  currentLocation: CodeNavigationHistoryLocation | null;
  navigating: boolean;
};

type Options = {
  scopeKey: string;
  onNavigate: (location: CodeNavigationHistoryLocation) => boolean | Promise<boolean>;
};

type ShortcutEvent = Pick<KeyboardEvent, "altKey" | "ctrlKey" | "key" | "metaKey" | "shiftKey">;

function emptyHistoryState(): HistoryState {
  return {
    backStack: [],
    forwardStack: [],
    currentLocation: null,
    navigating: false,
  };
}

function normalizeLocation(location: CodeNavigationHistoryLocation) {
  const path = String(location.path || "").trim();
  if (!path) {
    return null;
  }
  return {
    path,
    line: Math.max(1, Math.trunc(Number(location.line) || 1)),
    column: Math.max(1, Math.trunc(Number(location.column) || 1)),
  };
}

function locationsEqual(
  left: CodeNavigationHistoryLocation | null | undefined,
  right: CodeNavigationHistoryLocation | null | undefined,
) {
  return Boolean(
    left
    && right
    && left.path === right.path
    && left.line === right.line
    && left.column === right.column,
  );
}

function appendUnique(
  stack: CodeNavigationHistoryLocation[],
  location: CodeNavigationHistoryLocation,
) {
  if (locationsEqual(stack.at(-1), location)) {
    return stack;
  }
  return [...stack, location].slice(-CODE_NAVIGATION_HISTORY_LIMIT);
}

export function useCodeNavigationHistory({ scopeKey, onNavigate }: Options) {
  const [state, setState] = useState<HistoryState>(emptyHistoryState);
  const stateRef = useRef(state);
  const onNavigateRef = useRef(onNavigate);
  onNavigateRef.current = onNavigate;

  const commitState = useCallback((next: HistoryState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const reset = useCallback(() => {
    commitState(emptyHistoryState());
  }, [commitState]);

  useEffect(() => {
    reset();
  }, [reset, scopeKey]);

  const recordNavigation = useCallback((
    source: CodeNavigationHistoryLocation,
    target: CodeNavigationHistoryLocation,
  ) => {
    if (stateRef.current.navigating) {
      return false;
    }
    const normalizedSource = normalizeLocation(source);
    const normalizedTarget = normalizeLocation(target);
    if (!normalizedSource || !normalizedTarget) {
      return false;
    }
    const nextBackStack = locationsEqual(normalizedSource, normalizedTarget)
      ? stateRef.current.backStack
      : appendUnique(stateRef.current.backStack, normalizedSource);
    commitState({
      backStack: nextBackStack,
      forwardStack: [],
      currentLocation: normalizedTarget,
      navigating: false,
    });
    return true;
  }, [commitState]);

  const goBack = useCallback(async () => {
    const snapshot = stateRef.current;
    const destination = snapshot.backStack.at(-1);
    if (snapshot.navigating || !destination) {
      return false;
    }
    commitState({ ...snapshot, navigating: true });
    let opened = false;
    try {
      opened = await onNavigateRef.current(destination);
    } catch {
      opened = false;
    }
    if (!opened) {
      commitState({ ...snapshot, navigating: false });
      return false;
    }
    commitState({
      backStack: snapshot.backStack.slice(0, -1),
      forwardStack: snapshot.currentLocation
        ? appendUnique(snapshot.forwardStack, snapshot.currentLocation)
        : snapshot.forwardStack,
      currentLocation: destination,
      navigating: false,
    });
    return true;
  }, [commitState]);

  const goForward = useCallback(async () => {
    const snapshot = stateRef.current;
    const destination = snapshot.forwardStack.at(-1);
    if (snapshot.navigating || !destination) {
      return false;
    }
    commitState({ ...snapshot, navigating: true });
    let opened = false;
    try {
      opened = await onNavigateRef.current(destination);
    } catch {
      opened = false;
    }
    if (!opened) {
      commitState({ ...snapshot, navigating: false });
      return false;
    }
    commitState({
      backStack: snapshot.currentLocation
        ? appendUnique(snapshot.backStack, snapshot.currentLocation)
        : snapshot.backStack,
      forwardStack: snapshot.forwardStack.slice(0, -1),
      currentLocation: destination,
      navigating: false,
    });
    return true;
  }, [commitState]);

  const handleShortcut = useCallback((event: ShortcutEvent) => {
    if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return false;
    }
    if (event.key === "ArrowLeft" && stateRef.current.backStack.length > 0 && !stateRef.current.navigating) {
      void goBack();
      return true;
    }
    if (event.key === "ArrowRight" && stateRef.current.forwardStack.length > 0 && !stateRef.current.navigating) {
      void goForward();
      return true;
    }
    return false;
  }, [goBack, goForward]);

  return {
    backStack: state.backStack,
    forwardStack: state.forwardStack,
    currentLocation: state.currentLocation,
    navigating: state.navigating,
    canGoBack: state.backStack.length > 0 && !state.navigating,
    canGoForward: state.forwardStack.length > 0 && !state.navigating,
    recordNavigation,
    goBack,
    goForward,
    handleShortcut,
    reset,
  };
}
