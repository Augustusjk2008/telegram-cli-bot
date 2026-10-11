import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";
import type { WebBotClient } from "../services/webBotClient";

const client = {} as WebBotClient;

describe("MediaView", () => {
  it.each([
    ["audio", "plugin-audio", "music.mp3"],
    ["video", "plugin-video", "movie.mp4"],
  ] as const)("renders a native %s player for %s", (mediaType, testId, path) => {
    render(
      <PluginViewSurface
        botAlias="main"
        client={client}
        inputPayload={{ path }}
        view={{
          pluginId: "media-player",
          viewId: "player",
          title: "音视频播放",
          renderer: "media",
          mode: "snapshot",
          payload: { path, mediaType },
        }}
      />,
    );

    const player = screen.getByTestId(testId);
    expect(player).toHaveAttribute("controls");
    expect(player).toHaveAttribute("src", `/api/bots/main/files/download?filename=${path}&inline=1`);
  });
});
