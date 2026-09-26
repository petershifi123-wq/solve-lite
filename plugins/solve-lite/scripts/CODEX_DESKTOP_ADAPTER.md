# Solve Lite → Codex Desktop adapter

`scripts/codex_desktop_adapter.py` is the only adapter surface for the Codex
Desktop host. It speaks the official Codex interfaces and nothing else:

* `codex plugin add|remove|list` for plugin lifecycle,
* Codex app-server JSON-RPC over stdio (`hooks/list`, `config/read`,
  `plugin/list`, `config/batchWrite`) — the same RPC the Desktop app uses.

It never writes hook trust. Codex stores hook trust in
`hooks.state.<hook key>.trusted_hash` and only a visible user approval may set
it, so `install` and `doctor` stop at `READY_FOR_PETER_HOOK_APPROVAL` and print
the exact key and hash a human has to approve.

## Commands

```bash
# verify install, discovery, trust, project trust, dispatch and real invocation
/usr/bin/python3 scripts/codex_desktop_adapter.py doctor --cwd "$PWD"

# skip the one-turn end-to-end probe (saves one model call)
/usr/bin/python3 scripts/codex_desktop_adapter.py doctor --cwd "$PWD" --no-dispatch-probe

# record the reward-ledger baseline, then prove the ordinary Desktop session
/usr/bin/python3 scripts/codex_desktop_adapter.py snapshot --out /tmp/solve-lite-ledger-baseline.json
/usr/bin/python3 scripts/codex_desktop_adapter.py doctor --cwd "$PWD" \
    --ledger-baseline /tmp/solve-lite-ledger-baseline.json

# extract the visible contract from one session rollout (raw ordinary-session evidence)
/usr/bin/python3 scripts/codex_desktop_adapter.py rollout-check --session <SESSION_ID>

# offline self-check of the ordinary-session gate
/usr/bin/python3 scripts/test_codex_desktop_adapter.py

# install or refresh the plugin (backs up config.toml + marketplace.json first)
/usr/bin/python3 scripts/codex_desktop_adapter.py install

# remove the plugin and its cache (backup first, never touches other plugins)
/usr/bin/python3 scripts/codex_desktop_adapter.py uninstall --yes
```

Exit codes: `0` = PASS, `2` = READY_FOR_PETER_HOOK_APPROVAL / GATE_AWAITING_ORDINARY_SESSION, `1` = FAIL.

## What doctor proves

| check | meaning |
| --- | --- |
| `ADAPTER_SOURCE` | manifest, hook command, runtime config and ABI healthcheck |
| `PLUGIN_INSTALLED` / `PLUGIN_ENABLED` | `plugin/list` state |
| `SOURCE_CACHE_IDENTITY` | source plugin tree == materialized cache (byte identical) |
| `HOST_DISCOVERY` | `hooks/list` returns exactly **one** Solve Lite hook (no duplicates) |
| `ROUTER_REGISTERED` | key/event/command/matcher of the registered router hook |
| `HOOK_TRUST` | `trusted`/`managed` = approved, otherwise the human gate |
| `RESTART_PERSISTENCE` | persisted `trusted_hash` equals the hook's `current_hash` |
| `PROJECT_TRUST` | Codex only executes hooks inside a trusted project |
| `DISPATCH_PROBE` | one real model turn through the plugin hook (trust bypassed, isolated reward ledger) must show localized percentages, token status and one `+5` footer — **envelope evidence only, never product evidence** |
| `REAL_INVOKE` | production invocation ledger; with `--ledger-baseline` it must have **advanced**, otherwise it is only a legacy view |
| `ORDINARY_SESSION` | the four-flag product gate: exactly **one** new production invocation, its session must come from the Desktop app, and the **visible assistant message** must carry the Chinese percentage labels, the token status, the `+5` delta and the running total with a single latency line |

`ORDINARY_SESSION` deliberately reads `~/.codex/sessions/**/rollout-*.jsonl`. The hook
injects its contract as a `developer` message in that rollout, which is textually
identical to the visible answer, so the check only accepts `response_item` messages
with `role=assistant`: an injected contract can never pass as a user-visible answer.

## Token truth (no static token sentence)

The visible token settlement is derived per turn, never hard-coded:

| trace | rendered line |
| --- | --- |
| no packing receipt in this trace (the ordinary `route_prompt` path) | `Token：0（无可压缩上下文）` |
| a packing receipt in the same trace | `Token：输入 N · 输出 M · 压缩 D · 凭据 evt_…` |

`hooks/user_prompt_submit.py` builds both from `_token_settlement(result, locale=…)` and
stores the full numeric settlement (status, measurement source, counts, receipt id,
`provider_savings_status: NOT_MEASURED`) in the invocation audit record, so every
displayed number can be re-derived. Provider-side savings are never derived from local
counts. `scripts/test_token_truth.py` proves the zero case, a real multi-turn pack with a
positive auditable delta, and that the retired hard-coded sentence is gone.

## Layout boundary (measured, do not "fix" it back)

`hooks/hooks.json` is the only hook manifest; `.codex-plugin/plugin.json` is the
load-bearing manifest that declares it. A root `plugin.json` must **not** be added: on
codex-cli `0.155.0-alpha.16.4` it switches the plugin to the Agent Plugins loader, which
exposes **no** hooks at all (ten layouts measured in `LAYOUT_MATRIX.json`). `ADAPTER_SOURCE`
fails loudly if a root `plugin.json` ever appears.

The dispatch probe runs in a throwaway project with an isolated
`SOLVE_LITE_WORKSPACE`, so the production reward ledger is untouched; the
project-trust row Codex auto-persists for that throwaway directory is removed
again through `config/batchWrite`.

## Approval step (human, required once)

The Hooks panel only loads when the app knows at least one project root
(`hooks/list` needs `cwds`); with no project open it stays on
`正在加载钩子… / Loading hooks…`. So:

1. Codex Desktop → open an ordinary session in a **trusted** project first.
2. Settings (设置) → Hooks (钩子). The Solve Lite hook shows up under
   "From Plugins / 来自插件" as event `UserPromptSubmit` with a `新钩子 / New hook`
   badge.
3. Click the **`信任 / Trust`** button in that hook row (next to the disabled toggle).
   Only this visible click writes `hooks.state.<key>.trusted_hash`; the adapter
   never writes it.
4. Restart Codex Desktop, open a fresh ordinary session, ask one bounded question and
   confirm the visible percentage line, token status and `+5` reward footer.
5. `snapshot` before the session and re-run `doctor --ledger-baseline …`;
   `HOOK_TRUST`, `RESTART_PERSISTENCE`, `ORDINARY_SESSION` and `REAL_INVOKE`
   must all be `PASS` for a product PASS.

## Rollback

Every `install`/`uninstall` writes a timestamped backup under
`~/Library/Application Support/OpenAI/Codex/solve-lite/adapter-backups/<utc>/`
(`config.toml`, `marketplace.json`, and the plugin cache for uninstall).
`uninstall` prints the exact restore command.

To drop only the adapter files, delete `scripts/codex_desktop_adapter.py`,
`scripts/CODEX_DESKTOP_ADAPTER.md`, `scripts/test_codex_desktop_adapter.py` and
`scripts/test_token_truth.py` from the plugin source **and** from the installed cache
(`~/.codex/plugins/cache/personal/solve-lite/<version>/scripts/`); hook trust and the
hook hash are unaffected because they are computed from `hooks/hooks.json`,
not from these scripts.
