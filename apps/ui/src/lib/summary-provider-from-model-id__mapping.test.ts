/**
 * Maps onboarding / settings summary model ids onto summaryProvider.
 */
import { describe, expect, it } from "vitest";
import { summaryProviderFromModelId } from "./summary-provider-from-model-id";

describe("summaryProviderFromModelId", () => {
  it.each([
    ["gemini-2.5-flash", "gemini"],
    ["gemini-2.5-pro", "gemini"],
    ["claude-sonnet-4-5", "anthropic"],
    ["gpt-4o", "openai"],
    ["llama3.2", "ollama"],
    ["gemma3:1b", "ollama"],
  ] as const)("maps %s → %s", (modelId, provider) => {
    expect(summaryProviderFromModelId(modelId)).toBe(provider);
  });
});
