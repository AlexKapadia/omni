/**
 * Derive summaryProvider from a model id prefix (onboarding + settings).
 * Closed mapping — unknown ids fall closed to ollama (local-first default).
 */
import type { SummaryProvider } from "./setup-settings-commands";

export function summaryProviderFromModelId(modelId: string): SummaryProvider {
  const id = modelId.trim().toLowerCase();
  if (id.startsWith("gemini-")) return "gemini";
  if (id.startsWith("claude-")) return "anthropic";
  if (id.startsWith("gpt-")) return "openai";
  if (id.startsWith("llama") || id.startsWith("gemma")) return "ollama";
  return "ollama";
}
