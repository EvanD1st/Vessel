# Inference gateway developer preview

`vessel.gateway.create_app` prepares a separate FastAPI service for a verified
OpenAI-compatible Chat Completions route. Fixture tests and a real Orbio inference
test now pass for GPT-4.1 Mini and GPT-4o Mini: model switching, text/tool streaming,
local tool execution/result round trips, controlled fallback and no midstream
replay. See [the live results and compatibility limits](gateway-live-20260914.md).
A subsequent native Cline text probe also succeeded through the gateway; native
tool execution and model switching remain pending. Public deployment, funding
balance and automatic recovery have not been verified by these tests.

The local companion remains a different service. Cline's OpenAI Compatible
provider accepts a base URL, API key and model ID. On a local VS Code extension
host, the test URL is `http://127.0.0.1:8091/v1`. Remote SSH, WSL or containers
may use a different host; loopback reachability requires separate verification.
[Cline provider configuration](https://docs.cline.bot/provider-config/openai-compatible)

## Factory contract

```python
import os
from vessel.gateway import UpstreamRoute, create_app

# `service` is the enrolled local Vessel service created by the CLI/application.
# Its authorizer must read current policy/lease/revocation authority on every call.
app = create_app(
    routes={
        "verified-route": UpstreamRoute(
            endpoint=os.environ["VESSEL_UPSTREAM_CHAT_ENDPOINT"],
            api_key=os.environ["VESSEL_UPSTREAM_API_KEY"],
            allowed_models=frozenset({"operator-verified-model"}),
            credential_version="1",
        ),
    },
    authorize=service.authorize_gateway,
    audit=service.audit_gateway,
)
```

The names in this example are local VESSEL configuration, not Orbio endpoint or
model names. Set the endpoint only after verifying the provider's supported
protocol. Import the factory in a separate Python module and serve its `app`
with Uvicorn. Use HTTPS termination when exposing the service, and configure
server/proxy request timeouts. Upstream credentials belong in environment/secret
management, never in checkpoint data, exports, browser storage or source files.

`authorize(token)` can be synchronous or asynchronous and returns a
`GatewayAdmission` or `None`, or raises `AuthorizationDenied`. It maps a dedicated
VESSEL bearer credential to trusted enrollment facts. The authorizer is
responsible for reading the current authoritative execution lease, policy,
credential revocation, and local/cloud authority mode. The factory checks active
status, known authority, positive revision/epoch, and equality with the
credential's epoch and policy revision. It rechecks after the request body and
after the admission receipt, before dispatch. Authority failure denies admission;
there is no stale cache fallback. A cloud-managed enrollment requires a real
cloud authority adapter; do not return local facts for it.

The optional `audit(event)` receives a `GatewayEvent` without prompt bodies,
upstream responses, API keys or client tokens. A callback failure blocks new
admissions. Events retain distinct enrollment, credential, owner, agent,
workspace, epoch, policy and route identifiers. Native request correlation is
unverified: `attribution_level` is always `enrollment`, `run_id` is always `None`,
and `cost` is always `None`. Client-provided run headers are not forwarded or
trusted. Without a durable callback, only the most recent 1,000 events remain in
memory. These receipts are not a reservation or spending-reconciliation ledger;
the gateway does not claim a hard monetary cap.

## Supported behavior

| Surface | Implemented behavior |
| --- | --- |
| `GET /health` | Minimal preview and accounting-health status; no secrets. |
| `GET /v1/models` | Current-authority authentication, allowed models and aliases with eligible candidates. |
| `POST /v1/chat/completions` | Dedicated bearer authentication, bounded JSON body, trusted route, current policy/epoch checks. |
| Streaming | Successful SSE/tool-call bytes retain their structure; configured secret occurrences are redacted even across chunks. |
| Upstream failures | Normalized errors; error response bodies/headers and provider SSE error frames are discarded. |
| Profiles | Optional owner-configured alias with 1–3 distinct allowlisted candidates. Authorization is rechecked for each attempt. |
| Fallback | Only explicit HTTP 500/502/503/504, or an initial complete SSE error carrying one of those codes, before response commitment. |
| Interruptions | No replay on uncertain transport/protocol/size errors or after commitment. Missing `[DONE]` remains uncertain. |
| Revocation | Denies the next admission; does not claim to cancel a request already sent or a native tool already running. |
| Credential replacement | Operator rebuilds route configuration with a new secret/version; dedicated VESSEL token lifetime remains an authority decision. |
| Orbio | Explicit unsupported capability adapter; no invented API requests. |

The request supports `model`, `messages`, `stream`, tool definitions/selection,
parallel tool calls, sampling controls, token limits, response format, seed,
stream options, log-probability fields, user and reasoning effort. Other top-level
fields and query parameters are rejected. Requests cannot provide an upstream
URL, key, route or run ID. Successful non-streaming JSON and SSE tool structures
are not translated between provider protocols.

Defaults are a 1 MiB request, an 8 MiB response/stream, four simultaneous requests
per service process, and a 60-second total upstream deadline across attempts. These
are process bounds, not global quotas. The configured route must use HTTPS,
standard port 443, no userinfo/query/fragment, and a `/chat/completions` endpoint.
Only explicitly configured URLs are used; redirects and environment proxies are
disabled. Administrators are responsible for choosing a trustworthy reachable
host. There are no default Orbio URLs or models. Fallback requires an explicit
profile and may incur provider charges for more than one attempt. Authentication,
funding, request errors and unscoped 429 rate limits do not switch models.

An upstream HTTP error may still incur cost. Transport failure, invalid protocol,
response-size overflow, client disconnect, and incomplete streams produce
uncertain receipts. Completed means that a response was received in the expected
protocol, not proof that a mission completed, cost was reconciled, or tool side
effects occurred. Raw successful model content is not a trusted instruction or
an authorization source.

## Cline gateway test setup

Direct OpenRouter configuration in Cline is the shortest path for the native
capture test. It does not route inference through VESSEL or establish spending
enforcement. Use the following optional flow only to test VESSEL routing.

After enrollment and a recorded native probe, configure the actual verified
model IDs in owner policy before starting the source run. The placeholders below
must be replaced; the preview has no default funded model or upstream key.

```powershell
.\vessel.cmd --state $vesselState policy --allow-model PRIMARY_MODEL_ID --allow-model SECONDARY_MODEL_ID
.\vessel.cmd --state $vesselState profile activate --alias vessel-auto --model PRIMARY_MODEL_ID --model SECONDARY_MODEL_ID
.\vessel.cmd --state $vesselState start $vesselProject --session OBSERVED_CLINE_TASK_ID
# In a separate terminal, keep the returned run/epoch alive:
.\vessel.cmd --state $vesselState companion --run RUN_ID --epoch EPOCH
```

If a run is already bound, do not start another. After a deliberate policy
change, inspect the run, explicitly revalidate it with `heartbeat --run RUN_ID
--epoch EPOCH --once --revalidate-policy`, and restart its companion if needed.
Issue a gateway token only while that run is active under current policy:

```powershell
.\vessel.cmd --state $vesselState issue-gateway-key --model PRIMARY_MODEL_ID --model SECONDARY_MODEL_ID
# Set VESSEL_UPSTREAM_KEY privately in this server's environment first.
.\vessel.cmd --state $vesselState gateway --upstream 'https://openrouter.ai/api/v1/chat/completions' --model PRIMARY_MODEL_ID --model SECONDARY_MODEL_ID
```

The upstream key belongs to the gateway's environment, not Cline, checkpoint
data or the dashboard. Do not paste it into source, reports or chat. In Cline
settings choose **OpenAI Compatible**, base URL `http://127.0.0.1:8091/v1`, the
dedicated token returned by `issue-gateway-key`, and model `vessel-auto`.
The upstream URL follows OpenRouter's
[Chat Completions API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion).
Configure context/output limits and tool/image capabilities conservatively for
every candidate. Those capabilities are not yet automatically validated.
[Cline custom-provider fields](https://docs.cline.bot/provider-config/openai-compatible)

Profiles are loaded when the gateway starts. Restart it after profile changes.
Epoch/policy changes or revocation invalidate a gateway token; issue a current
one after the owner-approved transition. Profiles do not modify Cline's direct
OpenRouter settings automatically.

Run one harmless live request before approving tool use. Verify the actual model
response, streaming, tool-call IDs and a follow-up request. These protocol checks
passed for the two models in the [live report](gateway-live-20260914.md), using an
isolated Python client. A native Cline text probe subsequently passed; its tool
execution and model switching checks remain pending.
The first native tool attempt printed its marker but lacked terminal completion
evidence, so capture correctly blocked further inference. Valid current gateway
credentials with unhealthy capture now receive HTTP 409 `capture_unhealthy`
with an instruction to review the companion's capture health. This does not
clear capture gaps or permit inference. Invalid or stale authority still fails
authorization. On Windows, verify VS Code shell integration using PowerShell 7
and inspect a real native exit-code receipt before accepting a command test.
The observed Orbio route rejects `parallel_tool_calls: false`; do not silently
drop that client instruction. Verify client settings or choose a compatible
provider. Follow-up probes also found that GPT-4.1 Mini requests with
`reasoning_effort: high` or `reasoning_effort: none` return HTTP 404, while the
same request with that field omitted succeeds. Disable inherited reasoning for
this test profile and verify native behavior; VESSEL does not silently remove
explicit reasoning controls. Receipts retain the requested
alias, attempted actual model and attempt index; they do not assert a funded
balance, native conversation attribution or reconciled cost.

Durable account/funding pauses, cooldowns, automatic capability validation,
provider-key onboarding and a routing configuration UI remain on the
[fallback roadmap](../VESSEL_FALLBACK_IMPLEMENTATION_PLAN.md). HTTP/SSE error
classification is deliberately conservative: shared credential/funding errors
and unscoped rate limits never trigger another model attempt. No automatic top-up
or credential rotation is implemented.

## Orbio capability boundary

`UnsupportedOrbioAdapter` reports credential validation, balance reads,
credential rotation and top-ups as unsupported. Each method raises
`UnsupportedCapability` without a network request. A later real adapter must
verify supported interfaces, authorization, response semantics and failure
behavior. No automatic rotation, top-up, wallet ownership or funding recovery is
enabled by the preview adapter.

## Verification and references

Run `.venv\Scripts\python.exe -m pytest tests/test_gateway.py`. Fixtures cover
split streaming tool calls, interruption/no fallback, missing completion marker,
secret redaction, non-stream errors, enrollment attribution, denied/stale/unknown
authority, revocation during upload and audit, accounting failure, body and
concurrency bounds, route validation, and unsupported Orbio capabilities.

The streaming implementation uses FastAPI's async-iterator `StreamingResponse`
and HTTPX manual streaming, with explicit response/client cleanup. These are
documented framework mechanisms, not evidence of provider compatibility.
[FastAPI custom responses](https://fastapi.tiangolo.com/advanced/custom-response/)
and [HTTPX async streaming](https://www.python-httpx.org/async/).
