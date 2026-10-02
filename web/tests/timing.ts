import { expect, type Locator, type Page } from "@playwright/test";

const names = { start: "片段開始邊界", victory: "勝利位置邊界" } as const;
type Edge = keyof typeof names;

export const edgeHandle = (scope: Page | Locator, edge: Edge) =>
  scope.getByRole("slider", { name: names[edge], exact: true });

/** Moves a trim handle the way a keyboard user does: Shift+Arrow is one second, Arrow one frame. */
export async function setEdge(scope: Page | Locator, edge: Edge, seconds: number) {
  const handle = edgeHandle(scope, edge);
  const delta = seconds - Number(await handle.getAttribute("aria-valuenow"));
  const whole = Math.trunc(delta);
  for (let step = 0; step < Math.abs(whole); step++) await handle.press(whole > 0 ? "Shift+ArrowRight" : "Shift+ArrowLeft");
  const frames = Math.round((delta - whole) * 30);
  for (let step = 0; step < Math.abs(frames); step++) await handle.press(frames > 0 ? "ArrowRight" : "ArrowLeft");
}

export async function expectEdge(scope: Page | Locator, edge: Edge, seconds: number) {
  await expect(edgeHandle(scope, edge)).toHaveAttribute("aria-valuenow", String(seconds));
}

export const postroll = (scope: Page | Locator) => scope.getByLabel("勝利後收尾", { exact: true });
