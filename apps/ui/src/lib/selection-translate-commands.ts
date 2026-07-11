/**
 * WS helper: `selection.translate` for Settings test-translate UX.
 */
import { requestSetupCommand } from "./setup-settings-transport";

export async function translateSelection(
  text: string,
  targetLang?: string,
  request: typeof requestSetupCommand = requestSetupCommand,
): Promise<string> {
  const payload: Record<string, unknown> = { text };
  if (targetLang !== undefined && targetLang.trim()) {
    payload.target_lang = targetLang.trim();
  }
  const result = await request("selection.translate", payload);
  const translated = result["translated"];
  if (typeof translated !== "string" || !translated.trim()) {
    throw new Error("Translation returned empty text");
  }
  return translated;
}
