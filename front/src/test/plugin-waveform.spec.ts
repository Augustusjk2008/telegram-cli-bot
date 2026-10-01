import { expect, test } from "@playwright/test";

test("offline waveform shell remains usable at narrow and wide widths", async ({ page }) => {
  const signals = Array.from({ length: 182 }, (_, index) => `<li class="signal">tb.dut.signal_${String(index + 1).padStart(3, "0")}</li>`).join("");
  await page.setContent(`
    <style>
      :root { --text: #eaf4ff; --surface: #0c1626; --surface-strong: #101d31; --border: #38506b; --accent: #6bd3ff; --muted: #9cb2ce; }
      * { box-sizing: border-box; } body { margin: 0; background: var(--surface); color: var(--text); font: 14px Segoe UI, sans-serif; }
      .waveform { display: grid; grid-template-columns: minmax(190px, 240px) minmax(0, 1fr); height: 100vh; min-width: 0; }
      .navigator { min-width: 0; overflow: auto; border-right: 1px solid var(--border); padding: 8px; }
      .signals { max-height: 70vh; overflow: auto; } .signal { padding: 3px; white-space: nowrap; }
      .content { min-width: 0; overflow: auto; } .toolbar, .status { padding: 8px; border-bottom: 1px solid var(--border); }
      .overview { width: 100%; height: 32px; background: var(--surface-strong); } .wave { min-width: 640px; padding: 24px; }
      @media (max-width: 700px) { .waveform { grid-template-columns: minmax(150px, 38vw) minmax(0, 1fr); } }
    </style>
    <section class="waveform" data-testid="waveform-shell">
      <aside class="navigator"><input aria-label="搜索信号" placeholder="搜索信号"><ul class="signals">${signals}</ul></aside>
      <main class="content"><div class="toolbar">适应全部　适应选中　游标 Δt</div><svg class="overview" aria-label="overview"><rect x="20" width="80" height="20"></rect></svg><div class="wave">PASS　当前窗口已降采样</div><div class="status">未记录信号</div></main>
    </section>
  `);
  for (const width of [390, 1280, 1440]) {
    await page.setViewportSize({ width, height: 720 });
    await expect(page.getByTestId("waveform-shell")).toBeVisible();
    expect(await page.getByTestId("waveform-shell").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await expect(page.getByLabel("overview")).toBeVisible();
  await expect(page.getByText("PASS")).toBeVisible();
  await expect(page.getByText("未记录信号")).toBeVisible();
  await page.getByLabel("搜索信号").fill("signal_181");
  await expect(page.locator(".signal").filter({ hasText: "signal_181" })).toBeVisible();
});
