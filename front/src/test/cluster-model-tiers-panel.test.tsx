import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ClusterModelTiersPanel } from "../components/ClusterModelTiersPanel";

test("cluster model tiers panel updates selected tier", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();

  render(
    <ClusterModelTiersPanel
      value={{ low: "", medium: "balanced-model", high: "" }}
      modelOptions={["fast-model", "balanced-model", "strong-model"]}
      onChange={onChange}
    />,
  );

  await user.selectOptions(screen.getByLabelText(/低档/), "fast-model");

  expect(onChange).toHaveBeenCalledWith({
    low: "fast-model",
    medium: "balanced-model",
    high: "",
  });
});
