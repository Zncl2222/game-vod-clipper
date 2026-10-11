/** Default visual model; a saved user choice is resolved by the caller first. */
export function preferredModel<T extends { id: string; is_default?: boolean; input_modalities?: string[] }>(models: T[]): T | undefined {
  const visual = models.filter(model => !model.input_modalities || model.input_modalities.includes("image"));
  return visual.find(model => model.id === "gpt-5.6-luna")
    ?? visual.find(model => model.is_default) ?? visual[0] ?? models[0];
}

export function readVerificationPreference(): boolean {
  try { return localStorage.getItem("bosscut:verify-with-sol") !== "false"; } catch { return true; }
}
