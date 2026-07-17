You are fixing TypeScript errors in the UI of a Tauri 2 + React app. Work ONLY inside apps/ui/src (and apps/ui/*.html or vite config only if strictly required). Do NOT run any git commands. Do NOT touch the engine/ directory or docs/.

GOAL: `npx tsc --noEmit` run from apps/ui must exit 0, AND `npm run -s test` (vitest) run from apps/ui must stay fully green (currently 1015 tests passing — do not break any).

There are currently 44 errors. The full list is in docs/progress/gate-tsc-errors.txt (read it). Categories:
1. exactOptionalPropertyTypes violations (TS2375/TS2322/TS2379): lucide-react icon components passed to props typed `ComponentType<{size?: number; className?: string}>` (settings-screen.tsx, dictation-history-screen.tsx, toggle-chip test) — fix by widening the prop type to accept lucide icons (e.g. `ComponentType<{size?: number | string; className?: string}>` or `LucideIcon`), NOT by casting each usage. Style/payload objects with `| undefined` members (coachmark.tsx, tooltip.tsx, meeting-detected-toast.tsx, meeting-board-panel.tsx, capture-protocol.ts, library-meeting-detail-pane.tsx) — build objects conditionally or spread-omit undefined fields; keep runtime behavior identical.
2. Readonly array mutation in src/lib/meetings-live-repository.ts (`.push` on readonly arrays) — build new arrays or use local mutable copies.
3. WebSocket factory type mismatches in src/captions/captions-engine-bridge.ts and src/meeting-toast/meeting-toast-engine-bridge.ts, plus a `.message` access on the wrong union arm in meeting-toast-engine-bridge.ts — align with how src/lib does it (look at existing working bridges, e.g. the engine bridge used by the pill, for the WebSocketLike pattern).
4. TS2556 spread-argument errors in test files — type the spread args as tuples.
5. Test fixture shape drift: several tests construct EngineSettings / onboarding store objects missing newly added fields — add the missing fields with sensible defaults matching the real types (find the type definitions and copy defaults from production code).
6. TS6133 unused declarations (step-features-tour.tsx onContinue, ask-screen.tsx provider, home-screen.tsx HelpCircle + filterMeetings, onboarding-wizard.tsx vaultConfigured) — remove the unused binding ONLY; if it is a prop in a component's props type that callers still pass, remove it from the destructuring or prefix appropriately after checking callers.
7. nav-rail.tsx TS2367 unintentional comparison — inspect and fix the type, not the comparison, unless the comparison is genuinely dead code.

HARD RULES:
- NO `// @ts-ignore`, `// @ts-expect-error`, `any` casts, or loosening tsconfig. Fix root causes.
- NO behavior changes. This is type-level repair only.
- After fixing, run BOTH commands and iterate until both are green: `npx tsc --noEmit` and `npm run -s test` (from apps/ui).
- Final message: state the exact final output of both commands (error count / test count).