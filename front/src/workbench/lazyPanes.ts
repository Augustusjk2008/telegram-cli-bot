import { lazy } from "react";
import { FRONTEND_FEATURE_FLAGS } from "../app/featureFlags";

const loadDebugPane = () => import("./DebugPane").then((module) => ({ default: module.DebugPane }));
const loadEditorPane = () => import("./EditorPane").then((module) => ({ default: module.EditorPane }));
const loadTerminalPane = () => import("./TerminalPane").then((module) => ({ default: module.TerminalPane }));
const loadGitScreen = () => import("../screens/GitScreen").then((module) => ({ default: module.GitScreen }));
const loadPluginsScreen = () => import("../screens/PluginsScreen").then((module) => ({ default: module.PluginsScreen }));
const loadSettingsScreen = () => import("../screens/SettingsScreen").then((module) => ({ default: module.SettingsScreen }));

if (!FRONTEND_FEATURE_FLAGS.routeLazyLoading) {
  void Promise.all([
    loadDebugPane(),
    loadEditorPane(),
    loadTerminalPane(),
    loadGitScreen(),
    loadPluginsScreen(),
    loadSettingsScreen(),
  ]);
}

export const LazyDebugPane = lazy(loadDebugPane);
export const LazyEditorPane = lazy(loadEditorPane);
export const LazyTerminalPane = lazy(loadTerminalPane);
export const LazyGitScreen = lazy(loadGitScreen);
export const LazyPluginsScreen = lazy(loadPluginsScreen);
export const LazySettingsScreen = lazy(loadSettingsScreen);
