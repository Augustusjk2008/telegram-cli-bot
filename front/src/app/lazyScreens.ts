import { lazy } from "react";
import { FRONTEND_FEATURE_FLAGS } from "./featureFlags";

const loadAdminCenterScreen = () => import("../screens/AdminCenterScreen").then((module) => ({ default: module.AdminCenterScreen }));
const loadBotListScreen = () => import("../screens/BotListScreen").then((module) => ({ default: module.BotListScreen }));
const loadDesktopBotManagerScreen = () => import("../screens/DesktopBotManagerScreen").then((module) => ({ default: module.DesktopBotManagerScreen }));
const loadFilesScreen = () => import("../screens/FilesScreen").then((module) => ({ default: module.FilesScreen }));
const loadGitScreen = () => import("../screens/GitScreen").then((module) => ({ default: module.GitScreen }));
const loadMobileDebugScreen = () => import("../screens/MobileDebugScreen").then((module) => ({ default: module.MobileDebugScreen }));
const loadPluginsScreen = () => import("../screens/PluginsScreen").then((module) => ({ default: module.PluginsScreen }));
const loadSettingsScreen = () => import("../screens/SettingsScreen").then((module) => ({ default: module.SettingsScreen }));
const loadTerminalScreen = () => import("../screens/TerminalScreen").then((module) => ({ default: module.TerminalScreen }));
const loadDesktopWorkbench = () => import("../workbench/DesktopWorkbench").then((module) => ({ default: module.DesktopWorkbench }));
const loadSoloWorkbench = () => import("../workbench/SoloWorkbench").then((module) => ({ default: module.SoloWorkbench }));

if (!FRONTEND_FEATURE_FLAGS.routeLazyLoading) {
  void Promise.all([
    loadAdminCenterScreen(),
    loadBotListScreen(),
    loadDesktopBotManagerScreen(),
    loadFilesScreen(),
    loadGitScreen(),
    loadMobileDebugScreen(),
    loadPluginsScreen(),
    loadSettingsScreen(),
    loadTerminalScreen(),
    loadDesktopWorkbench(),
    loadSoloWorkbench(),
  ]);
}

export const LazyAdminCenterScreen = lazy(loadAdminCenterScreen);
export const LazyBotListScreen = lazy(loadBotListScreen);
export const LazyDesktopBotManagerScreen = lazy(loadDesktopBotManagerScreen);
export const LazyFilesScreen = lazy(loadFilesScreen);
export const LazyGitScreen = lazy(loadGitScreen);
export const LazyMobileDebugScreen = lazy(loadMobileDebugScreen);
export const LazyPluginsScreen = lazy(loadPluginsScreen);
export const LazySettingsScreen = lazy(loadSettingsScreen);
export const LazyTerminalScreen = lazy(loadTerminalScreen);
export const LazyDesktopWorkbench = lazy(loadDesktopWorkbench);
export const LazySoloWorkbench = lazy(loadSoloWorkbench);
