import { useState } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeManagerScreen } from "../screens/ThemeManagerScreen";
import {
  BUILTIN_THEME,
  THEME_TOKENS,
  resolveAppearance,
} from "../theme/resolveAppearance";
import type {
  PersonalTheme,
  ThemeCreateInput,
  ThemeLibrary,
  ThemeUpdateInput,
} from "../theme/types";

const api = vi.hoisted(() => ({
  library: undefined as ThemeLibrary | undefined,
  publish: undefined as ((next: ThemeLibrary) => void) | undefined,
  canManage: true,
  createTheme: vi.fn(),
  updateTheme: vi.fn(),
  deleteTheme: vi.fn(),
  selectTheme: vi.fn(),
  reload: vi.fn(),
}));

vi.mock("../theme/resolveAppearance", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../theme/resolveAppearance")>();
  const opaque = actual.THEME_TOKENS.find(
    (token) => token.cssVariable && !token.derive && !token.allowAlpha,
  )!;
  const derived = actual.THEME_TOKENS.find((token) => token.derive)!;
  const alpha = actual.THEME_TOKENS.find(
    (token) => token.allowAlpha && token.key !== derived.key,
  )!;
  return { ...actual, THEME_TOKENS: [opaque, derived, alpha] };
});

vi.mock("../theme/AppearanceProvider", () => ({
  useAppearance: () => {
    const [library, setLibrary] = useState(api.library!);
    api.publish = setLibrary;
    const update = async (operation: () => Promise<ThemeLibrary>) => {
      const result = await operation();
      api.library = result;
      setLibrary(result);
      return result;
    };
    return {
      library,
      appearance: resolveAppearance(
        library.themes.find((theme) => theme.id === library.selectedThemeId) ||
          BUILTIN_THEME,
      ),
      loading: false,
      error: "",
      canManage: api.canManage,
      reload: async () => {
        await api.reload();
        setLibrary(api.library!);
      },
      createTheme: (input: Omit<ThemeCreateInput, "expectedRevision">) =>
        update(() => api.createTheme(input)),
      updateTheme: (
        id: string,
        input: Omit<ThemeUpdateInput, "expectedRevision">,
      ) => update(() => api.updateTheme(id, input)),
      deleteTheme: (id: string) => update(() => api.deleteTheme(id)),
      selectTheme: (id: string) => update(() => api.selectTheme(id)),
    };
  },
}));

const colorToken = THEME_TOKENS.find(
  (token) => token.cssVariable && !token.derive && !token.allowAlpha,
)!;
const derivedToken = THEME_TOKENS.find((token) => token.derive)!;
const alphaToken = THEME_TOKENS.find(
  (token) => token.allowAlpha && token.key !== derivedToken.key,
)!;
const customTheme = (): PersonalTheme => ({
  ...BUILTIN_THEME,
  id: "theme_personal",
  name: "我的纸感",
  readonly: false,
  version: 1,
  appearance: { colors: { scheme: "light", overrides: {} } },
});
const libraryWith = (theme = customTheme()): ThemeLibrary => ({
  schemaVersion: 1,
  revision: 1,
  selectedThemeId: theme.id,
  themes: [BUILTIN_THEME, theme],
});
const hexInput = () =>
  screen.getByRole("textbox", { name: `${colorToken.label} HEX` });

beforeEach(() => {
  vi.clearAllMocks();
  api.library = libraryWith();
  api.canManage = true;
  api.reload.mockResolvedValue(undefined);
  api.updateTheme.mockImplementation(
    async (id: string, input: Omit<ThemeUpdateInput, "expectedRevision">) => ({
      ...api.library!,
      revision: api.library!.revision + 1,
      selectedThemeId: input.activate ? id : api.library!.selectedThemeId,
      themes: api.library!.themes.map((theme) =>
        theme.id === id
          ? {
              ...theme,
              name: input.name ?? theme.name,
              appearance: input.appearance ?? theme.appearance,
              version: theme.version + 1,
            }
          : theme,
      ),
    }),
  );
  api.createTheme.mockImplementation(
    async (input: Omit<ThemeCreateInput, "expectedRevision">) => {
      const created = {
        ...customTheme(),
        id: "theme_created",
        name: input.name,
        appearance: input.appearance || customTheme().appearance,
      };
      return {
        ...api.library!,
        revision: api.library!.revision + 1,
        themes: [...api.library!.themes, created],
        selectedThemeId: input.activate
          ? created.id
          : api.library!.selectedThemeId,
      };
    },
  );
  api.deleteTheme.mockImplementation(async (id: string) => ({
    ...api.library!,
    revision: api.library!.revision + 1,
    selectedThemeId: BUILTIN_THEME.id,
    themes: api.library!.themes.filter((theme) => theme.id !== id),
  }));
  api.selectTheme.mockImplementation(async (id: string) => ({
    ...api.library!,
    revision: api.library!.revision + 1,
    selectedThemeId: id,
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("个人主题管理", () => {
  it("keeps edits local, retains the last valid preview for invalid input, and discards without a write", async () => {
    const rootStyle = document.documentElement.getAttribute("style");
    const rootTheme = document.documentElement.getAttribute("data-theme");
    render(<ThemeManagerScreen />);
    const preview = screen.getByTestId("theme-local-preview");
    expect(preview).toHaveAttribute("data-style-profile", "paper");
    expect(preview).toHaveAttribute("data-motion-profile", "paper");
    expect(preview).toHaveAttribute("data-color-scheme", "light");
    expect(preview.style.colorScheme).toBe("light");
    const original = preview.style.getPropertyValue(colorToken.cssVariable!);
    fireEvent.change(hexInput(), { target: { value: "#123456" } });
    await waitFor(() =>
      expect(
        preview.style.getPropertyValue(colorToken.cssVariable!).toLowerCase(),
      ).toBe("#123456ff"),
    );
    fireEvent.change(hexInput(), { target: { value: "#12x" } });
    expect(hexInput()).toHaveValue("#12x");
    expect(hexInput()).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存并应用" })).toBeDisabled();
    expect(
      preview.style.getPropertyValue(colorToken.cssVariable!).toLowerCase(),
    ).toBe("#123456ff");
    expect(document.documentElement.getAttribute("style")).toBe(rootStyle);
    expect(document.documentElement.getAttribute("data-theme")).toBe(rootTheme);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "放弃更改",
      }),
    );
    await waitFor(() =>
      expect(preview.style.getPropertyValue(colorToken.cssVariable!)).toBe(
        original,
      ),
    );
    expect(api.updateTheme).not.toHaveBeenCalled();
    expect(api.createTheme).not.toHaveBeenCalled();
    expect(api.selectTheme).not.toHaveBeenCalled();
  });

  it.each([
    new Error("连接中断"),
    Object.assign(new Error("revision conflict"), { status: 409 }),
  ])("preserves the draft on failure and reload: %s", async (failure) => {
    api.updateTheme.mockRejectedValueOnce(failure);
    render(<ThemeManagerScreen />);
    fireEvent.change(hexInput(), { target: { value: "#334455" } });
    fireEvent.change(screen.getByLabelText("主题名称"), {
      target: { value: "保留我的草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("草稿已保留");
    expect(screen.queryByText("主题已保存。")).not.toBeInTheDocument();
    api.library = {
      ...api.library!,
      revision: 2,
      themes: [BUILTIN_THEME, { ...customTheme(), name: "其他页面的名称" }],
    };
    fireEvent.click(screen.getByRole("button", { name: "重新加载主题库" }));
    expect(api.reload).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "保留草稿并重载",
      }),
    );
    await waitFor(() => expect(api.reload).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("主题名称")).toHaveValue("保留我的草稿");
    expect(hexInput()).toHaveValue("#334455");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "保存" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("主题已保存。")).toBeInTheDocument();
    expect(api.updateTheme).toHaveBeenLastCalledWith(
      "theme_personal",
      expect.objectContaining({
        name: "保留我的草稿",
        activate: false,
        expectedRevision: 2,
      }),
    );
  });

  it("copies a builtin into a draft and creates plus activates it in one transaction", async () => {
    api.library = {
      schemaVersion: 1,
      revision: 1,
      selectedThemeId: BUILTIN_THEME.id,
      themes: [BUILTIN_THEME],
    };
    render(<ThemeManagerScreen />);
    expect(hexInput()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "复制后编辑" }));
    expect(api.createTheme).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("主题名称"), {
      target: { value: "夜读" },
    });
    fireEvent.change(screen.getByLabelText("明暗模式"), {
      target: { value: "dark" },
    });
    fireEvent.change(hexInput(), { target: { value: "#223344" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并应用" }));
    expect(await screen.findByText("主题已保存并应用。")).toBeInTheDocument();
    expect(api.createTheme).toHaveBeenCalledExactlyOnceWith({
      schemaVersion: 1,
      expectedRevision: 1,
      sourceId: BUILTIN_THEME.id,
      name: "夜读",
      appearance: {
        colors: {
          scheme: "dark",
          overrides: { [colorToken.key]: "#223344FF" },
        },
      },
      activate: true,
    });
    expect(api.selectTheme).not.toHaveBeenCalled();
    expect(api.updateTheme).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "已应用" })).toBeDisabled();
  });

  it("updates an existing theme with activate, while ordinary save keeps the current selection", async () => {
    api.library!.selectedThemeId = BUILTIN_THEME.id;
    render(<ThemeManagerScreen />);
    fireEvent.click(screen.getByRole("button", { name: /我的纸感/ }));
    fireEvent.change(screen.getByLabelText("主题名称"), {
      target: { value: "重命名主题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("主题已保存。");
    expect(api.library!.selectedThemeId).toBe(BUILTIN_THEME.id);
    fireEvent.change(hexInput(), { target: { value: "#345678" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并应用" }));
    await screen.findByText("主题已保存并应用。");
    expect(api.updateTheme).toHaveBeenLastCalledWith(
      "theme_personal",
      expect.objectContaining({ name: "重命名主题", activate: true }),
    );
    expect(api.library!.selectedThemeId).toBe("theme_personal");
    expect(api.selectTheme).not.toHaveBeenCalled();
  });

  it("guards closing and browser navigation, and only closes after a successful save", async () => {
    const onClose = vi.fn();
    render(<ThemeManagerScreen onClose={onClose} />);
    fireEvent.change(hexInput(), { target: { value: "#112233" } });
    const beforeUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "关闭主题管理" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "继续编辑",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(hexInput()).toHaveValue("#112233");
    api.updateTheme.mockRejectedValueOnce(new Error("保存失败"));
    fireEvent.click(screen.getByRole("button", { name: "关闭主题管理" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "保存后离开",
      }),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("dialog")).getByRole("alert"),
      ).toHaveTextContent("草稿已保留"),
    );
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "保存后离开",
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    const afterSave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(afterSave);
    expect(afterSave.defaultPrevented).toBe(false);
  });

  it("respects alpha restrictions and clears overrides when restoring inheritance", async () => {
    const rootStyle = document.documentElement.getAttribute("style");
    render(<ThemeManagerScreen />);
    expect(
      screen.queryByRole("slider", { name: `${colorToken.label} 不透明度` }),
    ).not.toBeInTheDocument();
    fireEvent.change(hexInput(), { target: { value: "#12345680" } });
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: `${colorToken.label} 恢复默认` }),
    );
    fireEvent.change(
      screen.getByRole("slider", { name: `${alphaToken.label} 不透明度` }),
      { target: { value: "50" } },
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: `${derivedToken.label} HEX` }),
      { target: { value: "#445566" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: `${derivedToken.label} 恢复跟随` }),
    );
    expect(document.documentElement.getAttribute("style")).toBe(rootStyle);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("主题已保存。");
    const overrides =
      api.updateTheme.mock.calls[0][1].appearance.colors.overrides;
    expect(Object.keys(overrides)).not.toContain(derivedToken.key);
    expect(Object.keys(overrides)).not.toContain(colorToken.key);
    expect(overrides[alphaToken.key]).toMatch(/80$/);
    fireEvent.click(screen.getByRole("button", { name: "整份恢复纸感配色" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(api.updateTheme).toHaveBeenCalledTimes(2));
    expect(
      api.updateTheme.mock.calls[1][1].appearance.colors.overrides,
    ).toEqual({});
  });

  it("asks before deleting the active theme and uses the returned fallback selection", async () => {
    render(<ThemeManagerScreen />);
    fireEvent.click(screen.getByRole("button", { name: "删除主题" }));
    expect(api.deleteTheme).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "确认删除",
      }),
    );
    await screen.findByText("主题已删除。");
    expect(api.deleteTheme).toHaveBeenCalledExactlyOnceWith("theme_personal");
    expect(api.library!.selectedThemeId).toBe(BUILTIN_THEME.id);
    expect(
      screen.getByRole("button", { name: "复制后编辑" }),
    ).toBeInTheDocument();
  });

  it("guards host navigation with save, discard and continue editing", async () => {
    const leave = vi.fn();
    const { unmount } = render(<ThemeManagerScreen />);
    fireEvent.change(hexInput(), { target: { value: "#224466" } });
    const request = new CustomEvent("theme-manager-before-leave", {
      cancelable: true,
      detail: leave,
    });
    act(() => {
      window.dispatchEvent(request);
    });
    expect(request.defaultPrevented).toBe(true);
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "继续编辑",
      }),
    );
    expect(leave).not.toHaveBeenCalled();
    act(() => {
      window.dispatchEvent(
        new CustomEvent("theme-manager-before-leave", {
          cancelable: true,
          detail: leave,
        }),
      );
    });
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "放弃更改",
      }),
    );
    expect(leave).toHaveBeenCalledTimes(1);
    expect(api.updateTheme).not.toHaveBeenCalled();
    unmount();
    const afterUnmount = new CustomEvent("theme-manager-before-leave", {
      cancelable: true,
      detail: leave,
    });
    window.dispatchEvent(afterUnmount);
    expect(afterUnmount.defaultPrevented).toBe(false);
  });

  it("holds host navigation during saving and continues without saving twice", async () => {
    let resolveSave!: (library: ThemeLibrary) => void;
    api.updateTheme.mockImplementationOnce(
      () =>
        new Promise<ThemeLibrary>((resolve) => {
          resolveSave = resolve;
        }),
    );
    const leave = vi.fn();
    render(<ThemeManagerScreen />);
    fireEvent.change(screen.getByLabelText("主题名称"), {
      target: { value: "保存中的主题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    const request = new CustomEvent("theme-manager-before-leave", {
      cancelable: true,
      detail: leave,
    });
    act(() => {
      window.dispatchEvent(request);
    });
    expect(request.defaultPrevented).toBe(true);
    expect(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "保存后离开",
      }),
    ).toBeDisabled();
    expect(leave).not.toHaveBeenCalled();
    await act(async () => {
      resolveSave({
        ...api.library!,
        revision: 2,
        themes: [BUILTIN_THEME, { ...customTheme(), name: "保存中的主题" }],
      });
    });
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "离开" }),
    );
    expect(leave).toHaveBeenCalledTimes(1);
    expect(api.updateTheme).toHaveBeenCalledTimes(1);
  });

  it("only discards the draft after the explicitly chosen reload succeeds", async () => {
    api.updateTheme.mockRejectedValueOnce(
      Object.assign(new Error("conflict"), { status: 409 }),
    );
    api.reload.mockRejectedValueOnce(new Error("重载失败"));
    render(<ThemeManagerScreen />);
    fireEvent.change(screen.getByLabelText("主题名称"), {
      target: { value: "需要保留的草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "重新加载主题库" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "放弃草稿并重载",
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("重载失败"),
    );
    expect(screen.getByLabelText("主题名称")).toHaveValue("需要保留的草稿");
    api.library = {
      ...api.library!,
      revision: 2,
      themes: [BUILTIN_THEME, { ...customTheme(), name: "服务器上的主题" }],
    };
    fireEvent.click(screen.getByRole("button", { name: "重新加载主题库" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "放弃草稿并重载",
      }),
    );
    await screen.findByText("主题库已重新加载。");
    expect(screen.getByLabelText("主题名称")).toHaveValue("服务器上的主题");
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(api.updateTheme).toHaveBeenCalledTimes(1);
  });

  it("saves against the draft revision when a background refresh arrives during editing", async () => {
    render(<ThemeManagerScreen />);
    fireEvent.change(hexInput(), { target: { value: "#335577" } });
    act(() => {
      api.library = { ...api.library!, revision: 5 };
      api.publish!(api.library);
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("主题已保存。");
    expect(api.updateTheme).toHaveBeenCalledWith(
      "theme_personal",
      expect.objectContaining({ expectedRevision: 1 }),
    );
  });

  it("coalesces preview changes into the latest animation frame and cancels the pending frame on unmount", () => {
    const frames = new Map<number, FrameRequestCallback>();
    let sequence = 0;
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frames.set(++sequence, callback);
      return sequence;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
      frames.delete(id);
    });
    const { unmount } = render(<ThemeManagerScreen />);
    fireEvent.change(hexInput(), { target: { value: "#112233" } });
    fireEvent.change(hexInput(), { target: { value: "#334455" } });
    expect(frames.size).toBe(1);
    act(() => {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach((callback) => callback(0));
    });
    expect(
      screen
        .getByTestId("theme-local-preview")
        .style.getPropertyValue(colorToken.cssVariable!)
        .toLowerCase(),
    ).toBe("#334455ff");
    fireEvent.change(hexInput(), { target: { value: "#556677" } });
    unmount();
    expect(frames.size).toBe(0);
  });
});
