# Native Cline recovery test — 13 September 2026

Status, rechecked 14 September: native source-to-destination recovery verified.
The selected recovery is `succeeded`; all nine destination tests passed, both
tasks are done, and the destination run is completed with a verified final
checkpoint. The user's Chrome screenshot confirms connection and the final
checkpoint without blockers; the Recovery-page status badge has not been shown. This is real
Cline activity, not a fixture, and applies to the inspected patched build below.

## Test workspace

- Workspace: `C:/Users/USER/Downloads/VESSEL/.cline-recovery-live-20260913/authentication-task`
- Private state: `C:/Users/USER/Downloads/VESSEL/.cline-recovery-live-20260913/private-state`
- VS Code window title: **VESSEL RECOVERY TEST**
- Active MCP server: `vessel-96dcf14f19a5`
- Cline: inspected 4.1.17 Windows SDK build with VESSEL schema 2 compatibility patch.
- Native source model: `aion-labs/aion-3.0-mini`, using the existing OpenAI-compatible provider setup.

The prior canary MCP server `vessel-857944557785` was temporarily disabled to
avoid reading another enrollment. Its entry is preserved in
`private-state/mcp-config-before-selection.json`. Provider settings were unchanged.

## Recorded source evidence

| Evidence | Result |
| --- | --- |
| Source task | `1789260154728_4cx4u` |
| Source run | `run_2bdd9c651cb443269e96b19925ba5ad6`, epoch 1 |
| MCP workspace status | Native receipt pair 10/11; correct enrolled project. |
| Native edits | Pairs 23/24 for `app.py` and 25/26 for `test_auth.py`. |
| Native tests | Pair 27/28; exact foreground pytest command; 5 passed, exit 0. |
| Test operation | `a7227e4e1192c167cf4c044deb28483c2b4b37b689662017694b13423477f0d0` |
| Source completion | Native stop event 29, user completion report, then user-reported PC shutdown. |
| Post-shutdown files | Exact SHA-256 match with the last automatic checkpoint. |
| Capture health | Healthy, no gaps, no unresolved operations. |
| Selected checkpoint | `checkpoint_dfafca82f2f34783bcf7e53afb71360a` |
| Checkpoint verification | Eligible, no blockers. |

At the source checkpoint, registration/login was recorded as done with the native
test receipt. Password reset was pending, with requirements for an expiring one-use demo token and tests
covering invalid, expired and reused tokens, old-password rejection and successful
login with the new password. No external email service or real user data is used.

Files and event history were preserved after the shutdown. The source remains
paused; the destination is now completed. Keep both test chats stopped.

## Destination handover

| Evidence | Result |
| --- | --- |
| Destination task | `1789323748156_tfvfa` |
| Native READY | Events 30–32, originally unbound; historical attribution preserved. |
| Destination run | `run_b42dd125ebc144f3b9934e568ebc9497`, epoch 2 |
| Recovery | `recovery_f200a2f427c16a086e03ee6d80cd14ed` |
| Capacity | User reports 3.6K used of 128.0K; essential handover is 2,987 UTF-8 bytes within a 24,000-byte budget. |
| Preflight | No integrity, workspace, environment or competing-session blockers. |
| Native retrieval | Pair 35/36 calls `vessel_get_recovery_context` with this exact recovery ID and returns the selected checkpoint and destination IDs. |
| Native continuation edits | Pairs 45/46, 47/48 and 49/50 add password-reset implementation to `app.py`. |
| Interruption | Provider `ECONNRESET` interrupted the first destination execution; the same root task resumed from its saved files. |
| Native test edits | Pairs 61/62 and 65/66 update `test_auth.py`. |
| Native acceptance tests | Pair 67/68; exact foreground pytest command; 9 passed, 2 upstream deprecation warnings in 4.15s, exit 0. |
| Acceptance operation | `2c9d86de603c00459ad45a5c8fc8a66033652ca4af406e38ffb1217064da7638` |
| Destination completion | Native stop 69, user completion report, all tasks done, owner-completed run. |
| Final checkpoint | `checkpoint_b550ea80ffe941bd98ddd0edff7ec9b1`; event watermark 69; eligible, no blockers. |
| Recovery status | `succeeded`, recorded after review of the native retrieval, edits and acceptance-test receipt. |

The destination reports the same model as the source. Its context limit was
confirmed by the user, with separate allowance for client tools, instructions and output.
[OpenRouter's model page](https://openrouter.ai/aion-labs/aion-3.0-mini-20260707)
advertises a 131,072-token context window; that alone does not verify the client's
configured capacity.

During inspection, native receipts 38 and 42 report a missing guessed test filename
and an attempt to read a directory as a file. Receipt 44 rejects an editor request
with a missing `new_text` argument. Receipt 60 rejects a test edit because its
search text was not found and explicitly reports no replacement. Owner
reconciliation records these known failures; they remain failed receipts and
are not success evidence. Corrected edits have their own successful receipts.

The provider disconnected after the implementation edits. A later partial Cline
reply incorrectly said it had only inspected files; the actual saved file and
native editor receipts establish that edits occurred. The same destination chat
resumed and completed its tests under SDK execution `run_oxnXC18A`. Its internal
conversation changed to `conv_1789325698990_h8jg0fp`, while the observed root task
remained `1789323748156_tfvfa`; every destination event belongs to epoch 2.

Reconstructing the files from the successful native edits matches their saved
redacted contents. Actual file bytes match automatic checkpoint
`checkpoint_fb404e5891f17e61d062d18f07b85f76` and the final stopped-writer checkpoint.
AST comparison confirms that registration/login definitions and all five original
tests are unchanged. Four new tests cover reset success, old-password rejection,
new-password login, invalid and expired tokens, and token reuse. Capture is
healthy with no gaps or unresolved operations. No native events were synthesized
or reassigned; owner reconciliation did not turn failed receipts into successes.

Evidence under the live test root: `source-evidence.json`,
`destination-evidence.json`, `recovery-result.json`, `destination-completion.json`
and `dashboard-evidence.json`.
The native recovery, dashboard connection and visible succeeded status on Chrome's
Recovery page are verified. The user's final screenshot shows the tested
destination and selected source checkpoint. Persistent pairing, renewal/reconnection
and device revocation also passed the separate
[local lifecycle checks](dashboard-lifecycle-live-20260914.md).
Broader production validation and upstream Cline compatibility remain separate work.

## Dashboard

The local web app runs at `http://localhost:3000`; the current bridge uses port
8766 with an eight-hour test lifetime. The private connection link is in
`private-state/bridge-current.log`; keep it private. The fixed local demo login
is documented in [local testing](local-testing.md). Processes must be restarted
after shutdown; saved evidence does not depend on their staying alive.

Chrome UI inspection was blocked because Computer Use could not verify its
current URL. Automatic approval review also blocked copying the private bridge
link into an additional file. The existing bridge output remains available;
manual Chrome verification was used instead. On 14 September the native UI
helper also failed to start with a missing kernel-assets path. The dashboard and
bridge listeners remain available. An authenticated read of the actual bridge's
`/v1/snapshot` returned HTTP 200, the expected enrollment/workspace, healthy capture,
the closed completed lease and this exact recovery as `succeeded`. The private
token was used only in memory and omitted from the saved evidence. The user then
confirmed connection and supplied a screenshot of the Checkpoints page showing
the exact final checkpoint `checkpoint_b550ea80ffe941bd98ddd0edff7ec9b1` with
"No recorded capture blockers". The screenshot is preserved as
`dashboard-checkpoints-confirmed.png` under the live test root. It does not show
the Recovery page. The user subsequently supplied an Overview screenshot showing
reconnection and healthy capture, followed by a Recovery screenshot showing
destination `1789323748156_tfvfa`, checkpoint suffix `71360a`, and the `succeeded`
badge. This completes the visual acceptance check for the tested recovery.
