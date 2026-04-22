import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PluginsScreen } from "../screens/PluginsScreen";

test("plugins screen toggles plugin enabled state and waveform LOD config", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateSpy = vi.spyOn(client, "updatePlugin");

  render(<PluginsScreen client={client} />);

  expect(await screen.findByText("Vivado Waveform")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "禁用 Vivado Waveform" }));

  await waitFor(() => {
    expect(updateSpy).toHaveBeenCalledWith("vivado-waveform", { enabled: false });
  });
  expect(await screen.findByText(/已禁用/)).toBeInTheDocument();

  await user.click(screen.getByLabelText("Vivado Waveform 启用 LOD"));

  await waitFor(() => {
    expect(updateSpy).toHaveBeenCalledWith("vivado-waveform", { config: { lodEnabled: false } });
  });
});
