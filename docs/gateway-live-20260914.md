# Real gateway inference test — 14 September 2026

**Passed for the gateway API:** two-model switching, incremental text/tool
streaming, actual local tool execution with a result round trip, controlled
fallback, and no replay after response commitment.

The test used the existing Cline-configured Orbio inference endpoint,
`https://api.orbio.so/api/v1/chat/completions`. It read the existing credential
privately, sent only canned test prompts, and did not change Cline configuration,
the successful recovery workspace, account balances, or funding settings.

## Verified model pair

| Check | GPT-4.1 Mini | GPT-4o Mini |
| --- | --- | --- |
| Requested and provider-reported model | `openai/gpt-4.1-mini` | `openai/gpt-4o-mini` |
| Normal completion | READY, normal stop | READY, normal stop |
| Text stream | 36 SSE data frames / 38 network chunks | 36 SSE data frames / 38 network chunks |
| First text chunk / total response | 1,100 ms / 1,620 ms | 2,386 ms / 2,617 ms |
| Tool stream | 13 data frames; call ID and JSON arguments retained | 13 data frames; call ID and JSON arguments retained |
| Actual execution | Python calculated 17 + 25 = 42 once | Python calculated 17 + 25 = 42 once |
| Tool result round trip | Matching tool-call ID returned; model reported 42 | Matching tool-call ID returned; model reported 42 |

The tool executor accepts only the named addition function and the exact approved
arguments. It refuses extra fields, unexpected functions, changed arguments and
duplicate IDs. It does not evaluate generated code, run shell commands, modify a
project or contact another service.

## Fallback and interruptions

- The owner-controlled test transport injected one HTTP 503 before the first
  attempt reached the provider. VESSEL then sent the same request to GPT-4o Mini,
  which returned a real completion. Receipts show attempts 1 and 2 and the actual
  selected model.
- A split initial SSE error with code 503 produced the same successful switch
  before response headers were committed. The second stream was real provider
  output and ended with `[DONE]`.
- After a real primary-provider stream began, the test transport interrupted it.
  VESSEL recorded an uncertain outcome, emitted no completion marker and made
  **no second attempt**. An uncertain stream is not promoted to success.
- Revoking the isolated test admission rejected a subsequent request without
  inference. The allowlisted models and test alias were also checked over HTTP.

The failures above were deliberately injected; this is not a claim that a natural
provider outage occurred. All successful model responses came from the real
upstream. The temporary gateway used actual loopback TCP and HTTPS upstream
requests, then stopped when the test finished.

## Compatibility findings

The provider rejected `parallel_tool_calls: false` with HTTP 404 and
`model_not_available`, even for GPT-4.1 Mini. A minimal tool request and named
`tool_choice` both worked. The final test omits the unsupported parallel-control
field and enforces one call in its local executor. VESSEL continues to forward
explicit client parameters unchanged; it does not silently discard tool policy.

Do not qualify every catalog model merely because it appears in `/models`.
The first Aion-3.0-Mini test returned normal text, but its counting stream reached
the 256-token test cap. Its tool request with the incompatible parallel-control
field failed. Aion has not been qualified by this workflow. Later tests require
a normal finish reason as well as `[DONE]` before passing completion.

These findings apply to the observed Orbio route today. They are not claims about
all providers serving these model IDs. Orbio documents its OpenAI-compatible
base URL on [its official site](https://www.orbio.so/). The request/stream/tool
shapes follow the [Chat Completions interface](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion),
[streaming protocol](https://openrouter.ai/docs/api/reference/streaming) and
[tool result workflow](https://openrouter.ai/docs/guides/features/tool-calling).

## Native setup follow-up: 15 September

The Cline gateway profile had inherited enabled reasoning with `high` effort.
After changing networks resolved a TLS connectivity failure, three bounded owner
HTTP probes against GPT-4.1 Mini isolated another route compatibility issue:
omitting `reasoning_effort` returned HTTP 200, `READY`, and a normal stop; adding
either `high` or `none` returned upstream HTTP 404. The requests otherwise used
the same prompt and 16-token output limit. See the
[comparison receipts](../.cline-gateway-live-20260914/reasoning-network-retest-20260915T074826Z.json).

Cline reasoning was disabled for this test profile. Explicit client fields are
still forwarded unchanged by VESSEL; an explicit `none` value is not equivalent
to omitting the field on this observed Orbio route. These three requests came
from the owner's diagnostic HTTP client and did not create native hook events.
The subsequent native Cline probe succeeded: the saved transcript contains
`GATEWAY_READY` under `vessel-auto`; native events 16–18 belong to the bound
conversation `1789413187806_58ozv`; and gateway request
`b3dc706f-ec19-4499-b41d-6ecab4becf78` completed with upstream HTTP 200,
GPT-4.1 Mini and 2,132 emitted bytes. Capture stayed healthy. See the
[first native success evidence](../.cline-gateway-live-20260914/native-first-success.json).
This is an observed canary association: gateway receipts still identify the
enrollment rather than a cryptographically bound native request, and hook model
fields remain unknown. Native tool execution and model switching remain pending.

The first native tool attempt exposed a terminal integration failure. Gateway
request `990c46cb-6118-44c8-b9f0-459b8d7f9503` completed with upstream HTTP 200
and produced the expected `run_commands` call. Native events 21–22 belong to
the same bound task. The terminal printed `VESSEL_GATEWAY_TOOL_PROBE`, but
Cline's log shows a four-second shell integration timeout and an unobserved
`sendText` execution. Its result omitted both an observed exit code and confirmed
completion. Event 22 correctly records `postToolUseFailure` with
`native_tool_exit_status_unavailable`; the tool test has **not passed**.
See the [sanitized terminal diagnostic](../.cline-gateway-live-20260914/native-terminal-diagnostic.json).

The following inference request was blocked by capture health, not by invalid
keys. VESSEL now returns HTTP 409 `capture_unhealthy`, with a fixed instruction
to review companion capture health, for otherwise-current authorized callers.
Invalid, revoked, stale, expired or paused authority remains denied before this
diagnostic is disclosed. Exception text and upstream details are not forwarded.

The test workspace now selects PowerShell 7.6.5 with VS Code shell integration
enabled. The previous terminal used Windows PowerShell 5.1; Windows integration
requires a supported shell such as `pwsh` ([VS Code documentation](https://code.visualstudio.com/docs/terminal/shell-integration)).
The canary uses an existing machine-local runtime path, which is not a portable
production prerequisite installer. Inspection of this VS Code build's terminal
launcher also found that `-NoProfile` prevents automatic integration injection;
the canary profile was corrected to use only `-NoLogo`. Existing terminals must
be replaced to use the corrected launch arguments. The owner subsequently
confirmed that VS Code's command marker reports success or exit code 0 for the
manual probe. Process inspection independently confirmed integration-script
injection in the new PowerShell terminals and no remaining probe process.
The [reviewed terminal repair](../.cline-gateway-live-20260914/terminal-repair-20260915.json)
reconciles the old operation as safe to retry and restores capture health through
the owner repair command. The original failed result is unchanged and still
cannot qualify as successful continuation. Native events remain at watermark 24;
the manual check and owner review added no native events. A new native Cline
tool receipt remains pending. The capture worker was restored after the local
processes stopped; the owner must restart the manual gateway before retrying.

After the admission fix, **314 automated tests passed** and Ruff passed for
`src`, `tests` and `scripts`. The full test output is saved in
[the regression log](../scratch/gateway-admission-regression-20260915.log).

## Evidence and rerun

- [Final sanitized report](../scratch/gateway-live-20260914/run-03/report.json):
  11 real upstream requests, 11 checks, 26 gateway admission/outcome receipts.
- [Actual local tool executions](../scratch/gateway-live-20260914/run-03/tool-receipts.jsonl).
- Earlier failed probes remain in `scratch/gateway-live-20260914/run-01` and
  `run-02`; diagnostic files record the incompatible request field.
- **69 automated checks passed** across `test_gateway.py` and
  `test_gateway_live_probe.py`; Ruff passes for the runner and tests.
- Native preservation checks still match: event watermark 69, successful recovery,
  healthy capture, original project hashes and MCP configuration.

The reusable runner defaults to a no-inference preview. Set the provider key
privately in `VESSEL_UPSTREAM_KEY`, then run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\verify_gateway_live.py --upstream https://api.orbio.so/api/v1/chat/completions --primary openai/gpt-4.1-mini --secondary openai/gpt-4o-mini --output scratch/gateway-live-new --run
```

Use a new output directory. The runner permits at most 12 real upstream attempts
by default (16 maximum), caps each response at 256 output tokens, and makes no
hidden transport retries. Provider charges may apply. Returned usage/cost fields
are observations, not reconciled billing or a hard monetary cap.

For the same explicitly configured local Cline provider, the alternative
`--cline-provider-file C:/Users/USER/.cline/data/settings/providers.json` reads
its existing key without printing or copying it. The supplied upstream must match
that file's exact configured base URL; another endpoint is refused.

## What this does not establish

This is an isolated gateway protocol test with explicit test authority. It is not
native Cline capture evidence and does not bind or resume a Cline conversation.
The normal `Vessel.authorize_gateway` lease/health path has fixture coverage;
a native Cline task routed through the gateway remains a separate integration
check. In particular, verify which tool-control parameters that Cline build sends
before using this route for real coding work.

No funding features were added. Wallet ownership, Orbio management APIs, spending
reservations/reconciliation, broader model capability validation and production
operation remain pending.
