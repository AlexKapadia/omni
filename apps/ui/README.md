# Omni UI — desktop shell

Tauri 2 shell (Rust) + React 18/TypeScript front end. This app is deliberately
thin: it renders state and relays commands. All capture, transcription,
indexing, and AI work happens in the Python **engine sidecar**, which the shell
spawns and supervises but never reimplements.

## Dev commands

```sh
pnpm install        # once
pnpm tauri dev      # full shell: window + tray + engine sidecar + vite dev server
pnpm dev            # front end only (no Tauri window, no sidecar)
pnpm typecheck      # tsc --noEmit (strict)
pnpm test           # vitest run
cargo check         # in src-tauri/ — compile-check the shell
```

Requires Node 22+, pnpm 10, Rust (MSVC toolchain), and `uv` on PATH for the
dev engine sidecar.

Run Rust builds (`cargo check`, `pnpm tauri dev`) from PowerShell or cmd, not
Git Bash: Git's coreutils `link.exe` shadows the MSVC linker on the Git Bash
PATH and every crate fails to link with `link: extra operand`.

## Architecture: shell vs engine sidecar

```
+--------------------------- Omni.exe (this app) ---------------------------+
|  Rust shell (src-tauri/)                                                  |
|    window + tray            engine_sidecar.rs supervisor                  |
|    single-instance          dev:  uv run python -m engine.server          |
|    global shortcuts (M-)    prod: omni-engine.exe (PyInstaller, M7)       |
|                             restart w/ backoff 1s..30s, kill tree on exit |
|  React front end (src/)                                                   |
|    lib/protocol.ts          pinned WS protocol v1 mirror (fail-closed     |
|                             validator — malformed frames are dropped)     |
|    lib/engine-connection.ts WS client: reconnect backoff, heartbeat       |
|                             staleness (5s), ping/pong latency sampling    |
|    lib/engine-status-store  zustand store the components render from      |
+----------------------------------------------------------------------------+
                                   | ws://127.0.0.1:8765/ws (loopback only)
                                   v
                       Python engine sidecar (engine/)
```

Key decisions:

- **One function decides the engine command** (`resolve_engine_command` in
  `src-tauri/src/engine_sidecar.rs`): dev runs the repo source via `uv`,
  release will run the PyInstaller binary. Packaging (M7) touches only that
  function. If the engine is missing, the shell logs and retries — it never
  crashes.
- **"Connected" means proven alive**: the status footer flips to connected
  only after a valid `engine.heartbeat`, not on socket open, and goes to
  disconnected if heartbeats stop for 5s (fail closed).
- **Latency is a first-class UI element**: a `ping` command is sent every 10s
  and the round-trip time renders live in the footer.
- **Design tokens**: `src/styles/tokens.css` is owned by the design agent and
  defines every CSS custom property (`--canvas`, `--ink`, `--grey-*`,
  `--font-*`, `--radius-*`, `--dur-*`, `--space-*`). Components consume only
  those variables — no raw hex/radius/duration values. Until that file exists
  the dev server will fail on the import; that is the intended contract, not
  a bug in this package.
- **Least privilege**: the webview capability grants `core:default` only; no
  plugin commands are exposed to the front end yet. CSP restricts network to
  the loopback engine socket.
- `tauri-plugin-updater` / `tauri-plugin-process` are dependencies only —
  configured at the packaging milestone (M7), not registered in the builder.
