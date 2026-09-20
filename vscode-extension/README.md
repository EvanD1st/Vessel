# VESSEL for VS Code + Cline

This local preview connects one trusted project to VESSEL's owner companion, encrypted checkpoints and reviewed recovery. The extension needs **local Windows x64 VS Code**, Python **3.11–3.14**, and the exact verified **Cline 4.1.17 Windows bundle**. Other Cline builds are blocked until separately verified. The extension never installs a provider key into project files or the browser.

## Install and set up

Install `vessel-companion-0.3.1.vsix` with **Extensions → … → Install from VSIX**. Open your project folder, trust it, then use the VESSEL activity icon or **VESSEL: Set Up VESSEL**. Select the one project to enroll. The installer verifies Python, stages a hash-checked offline runtime in VS Code private storage, inspects Cline's actual bundle, and shows all paths and processes before applying changes. It reuses an existing enrollment, mission, other MCP servers and owner data.

When prompted, open **Cline → MCP Servers → Configure MCP Servers** and select the exact settings file Cline opens. The extension does not guess a profile. Select the dashboard origin used by this project (`https://vessel-cont.duckdns.org` for the hosted dashboard, or your local development origin); companion pairing is restricted to that exact origin. Enter the Orbio key in the VS Code password field. After explicit consent it sends two small fixed `READY` requests through the local gateway, then stores the validated key in VS Code SecretStorage, scoped to this project. Provider charges may apply. Pick the verified `openai/gpt-4.1-mini` and `openai/gpt-4o-mini` as primary/fallback in either order. Fallback occurs only before response commitment; uncertain tool calls are not replayed. The historical gateway tests verified text and tool handling, but a complete native Cline-through-gateway model switch still needs the owner-operated canary.

Review the files, local ports and exact Cline patch before choosing Apply. VESSEL changes only its owned hooks/MCP entry and the hash-verified compatibility bundle, with an original backup for restoration. Setup does **not** bind an invented task or mark capture healthy.

Enable Cline hooks, reload VS Code while Cline is idle, then start a fresh Cline task in this project and send a harmless `READY` prompt. Use **Bind Observed Cline Task** to select its real ID. Send a second probe in the same task and inspect **VESSEL: Show Status**. The gateway remains local; to route Cline inference through it, choose **Configure Cline Inference**, copy the one-time VESSEL client key, then set Cline to OpenAI Compatible with the shown loopback URL, `vessel-auto` model and reasoning disabled. Never paste the Orbio key into that field.

For the first checkpoint, finish the Cline task and all tools, choose **Create Checkpoint**, enter concrete shutdown evidence, and review the result. Only integrity-eligible checkpoints can be selected for recovery. To recover, send a fresh probe in a new Cline task, choose **Recover Interrupted Task**, review the model, environment, context capacity and handover, then have that exact task retrieve the shown `vessel_get_recovery_context` ID. Confirm actual new work with **Confirm Observed Continuation**. The extension does not turn setup checks into native recovery evidence.

Status distinguishes Setup required, Unsupported Cline, Paused, Companion offline, Capture degraded and Protected. Protected requires a running capture worker, active lease, healthy native capture, compatible bundle, ready gateway and an eligible checkpoint. The companion and gateway can reconnect on VS Code restart for the explicitly selected project; they do not automatically bind another task. **Pause Protection** blocks new inference. **Forget Orbio Key** pauses/rotates gateway admission before deleting the secret. **Remove From Workspace** removes only unchanged owned configuration and keeps encrypted history. **Restore Original Cline Files** requires the verified backup and a review. The redacted diagnostic report contains no project content, absolute paths, prompts or keys.

## Build and test locally

From the repository root, a developer with Python and Node can run:

```powershell
python vscode-extension/scripts/build-runtime.py
cd vscode-extension
npm ci
npm run typecheck
npm run lint
npm test
npm run package:vsix
npm run test:package
```

The runtime builder downloads pinned Windows wheels **at developer build time** for Python 3.11–3.14. End-user setup is offline. The VSIX remains local and is not Marketplace published. Tests use disposable VS Code profiles and synthetic Cline fixtures; they never patch the installed Cline extension or issue paid provider calls. The provided owner CLI and web dashboard remain available independently.

This preview is not a claim of production readiness, arbitrary Cline compatibility, wallet ownership, automatic funding or universal provider support. The owner-operated native canary and clean Windows install are still release checks.
