# VS Code extension review — 16 September 2026

**The extension milestone in the build brief is not complete.** The TypeScript scaffold compiles, its packaged JavaScript activates, and the existing Python regression suite passes. The guided installation, trusted runtime, companion lifecycle, compatibility workflow, and evidence-backed checkpoint/recovery controls are not connected end to end.

This is a review of the current local checkout against the complete [build brief](C:/Users/USER/Downloads/VESSEL_VSCODE_EXTENSION_BUILD_BRIEF.md). Product source was not edited. Audit scripts and generated test output are in the ignored [review directory](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915). Results below were observed during 15–16 September; prior native canary results are explicitly identified as preserved evidence, not new tests.

## Findings requiring changes

1. **P1 — Status executes Python supplied by the opened project.** [pythonCli.ts:11](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/pythonCli.ts:11) resolves the executable script to `<workspace>/src/vessel/cli.py`. A disposable fixture containing a harmless script at that location ran successfully through the real `PythonCli.doctor()` subprocess. An ordinary application folder without that file cannot provide status; a project that contains it controls the invoked code. [extension.ts:17](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/extension.ts:17) also hardcodes `python` and silently selects the first workspace folder, discarding the detected interpreter. There is no managed, pinned VESSEL runtime in the extension. Resolve the CLI from trusted extension-managed artifacts and use the explicitly selected workspace only as data. The audit did not test execution inside a real restricted-mode VS Code window.

2. **P1 — Recovery status permits HTML/script injection.** [status.ts:77](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/status.ts:77) interpolates JSON into HTML without escaping it, while the panel enables scripts and has no content security policy. A harmless fixture value containing `</pre><script>…</script>` appeared as executable markup in the generated HTML. This audit inspected the markup; it did not execute an exploit. Escape/render data as text and restrict webview capabilities. This follows the [official VS Code webview security guidance](https://code.visualstudio.com/api/extension-guides/webview#security).

3. **P1 — Checkpoint creation is not connected to the selected enrollment and evidence.** [status.ts:49](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/status.ts:49) expects `doctor.capture.run_id`, which the current Python doctor response does not provide. It therefore uses `default`, calls an extension-relative Python script that does not exist in the VSIX, and supplies no private-state selection. The handler reports success for any resolved subprocess result: a fixture JSON error still produced “Checkpoint created successfully.” Preserve the existing source-stopped, admission, checkpoint-validation, and owner-review gates when wiring this command. Do not infer success merely from process completion.

4. **P1 — Cline compatibility is decided by version alone.** [cline.ts:13](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/cline.ts:13) labels version 4.1.17 `verified_patch` while its hash is literally `EXPECTED_HASH_HERE`. A fixture with that version and a nonexistent bundle path received that classification. An unknown version was correctly marked unsupported. The extension lacks the exact-build/OS verification, supported-capability evidence, inspect/plan/install/verify/restore workflow, update detection, and safe rollback required by the brief. The existing Python exact-hash patcher remains unchanged; this finding does not mean the audit patched or bypassed it.

5. **P1 — Approving setup does not configure VESSEL.** [extension.ts:21](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/extension.ts:21) checks requirements, displays a generic patch review, and ends with an information message. An executed fixture approval left only `requirements` completed and `currentStep` at `project`; no workspace was selected. Provider/model collection is not called from this path. No enrollment, MCP/hooks, runtime installation, companion startup, gateway validation, or first checkpoint follows. The review screen does not contain actual paths, files, processes, ports, or state changes.

6. **P2 — Key handling is only partially implemented and can misreport success.** [onboarding.ts:81](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/onboarding.ts:81) uses a password input and VS Code SecretStorage, which are appropriate primitives. However, a dummy invalid key was accepted and marked configured without provider verification or the specified reviewed consent flow. Cancelling replacement still showed a success message at [extension.ts:58](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/extension.ts:58). Forget only deletes the stored key; it has no admission pause or running-process credential lifecycle. [pythonCli.ts:26](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/pythonCli.ts:26) forwards raw stderr into user-facing errors; a dummy secret marker survived that path. No real provider credentials were used in these probes.

7. **P2 — Nine commands remain placeholders; status/recovery are not live controls.** The handlers in [extension.ts:37](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/extension.ts:37) for protect, recover, pause, resume, restart, compatibility review, restore, remove, and diagnostics only display “command triggered.” All nine were invoked in the fixture and behaved that way. Status starts at “Setup required” with no subsequent health observer. The recovery panel prints a fixed “No active interruption detected” message regardless of input. There is no reviewed destination selection, handover, context retrieval, or continuation confirmation UI.

8. **P2 — Welcome view registration and packaging are incomplete.** [package.json:86](C:/Users/USER/Downloads/VESSEL/vscode-extension/package.json:86) omits `type: "webview"` for the view registered with `registerWebviewViewProvider`; the separate status view has no registered provider. The [official webview-view sample](https://github.com/microsoft/vscode-extension-samples/blob/main/webview-view-sample/package.json) declares that view type explicitly. The referenced icon is absent. “Learn how it works” is an unhandled webview message, and the manifest’s alternative link points to `example.com`. The existing VSIX contains neither an extension README nor a Python package/wheel/runtime. Its JavaScript activation succeeded, which does not establish that onboarding or the views work.

9. **P2 — Durable setup, model verification, and lifecycle requirements are missing.** [onboarding.ts:48](C:/Users/USER/Downloads/VESSEL/vscode-extension/src/onboarding.ts:48) stores one unversioned progress object in global state, without workspace transaction identity, validated resume, change hashes, or rollback. The model picker uses a hardcoded Claude catalog with no Orbio availability/allowlist verification; it does enforce distinct selections in the tested fixture. There is no extension lifecycle state machine, single-instance supervision, bounded startup/stop, automatic reconnect, settings for autostart/close, or runtime upgrade/rollback. CLI execution has an output limit but no timeout; only prerequisite discovery has a timeout.

10. **P2 — The new dashboard changes fail lint and do not satisfy the explainer requirements.** [setup-guide/page.tsx:38](C:/Users/USER/Downloads/VESSEL/dashboard/app/setup-guide/page.tsx:38) has two unescaped-quote lint errors; [login-form.tsx:83](C:/Users/USER/Downloads/VESSEL/dashboard/app/login-form.tsx:83) adds a plain internal anchor rejected by the existing lint rules. Executing the compiled guide component with controlled hooks/timers produced eight steps, seven initially invisible, no static fallback, and no reduced-motion branch. Playback reaches the final step but remains “playing” with its interval active. The enabled CTA opens `vscode:extension/vessel.vessel`; the repository supplies no verified Marketplace listing and does not present the required disabled/preview state. Play/pause/replay labels are present. Browser layout, keyboard behavior, and actual Marketplace navigation were not tested.

11. **P2 — Coverage, CI packaging, and extension documentation are unfinished.** The four existing extension tests check presence, live Python detection, construction of a CLI object, and nonthrowing Cline detection. They do not test clean setup, failure recovery, secrets, conflicts, native health gates, rollback, upgrades, or VSIX contents. [CI](C:/Users/USER/Downloads/VESSEL/.github/workflows/ci.yml:43) runs extension compilation and these tests, but not extension lint or VSIX packaging/inspection. The `package` script bundles JavaScript only. There are no extension setup/limitations/rollback instructions in the root documentation, and no extension README. The current ignore rules also lack extension-specific exclusions for `out`, `.vscode-test`, and generated VSIX files.

## Coverage against all 15 deliverables

“Partial” means code exists but the complete requirement is not satisfied. “Missing” refers to the extension integration; some underlying Python capabilities already exist.

| # | Deliverable | Observed status |
|---|---|---|
| 1 | Extension and first-run onboarding | Partial: bundle activates; setup stops after requirements/approval. |
| 2 | Python 3.11+ detection and guidance | Partial: actual 3.11.9 detected with bounded subprocess discovery; no complete install/check-again guidance or use of the detected interpreter for operations. |
| 3 | Cline installation/version detection | Partial: missing/unknown-version handling exists; exact build/OS/capability verification is absent. |
| 4 | Reversible compatibility workflow | Missing from the extension; Python patcher exists but is not wired into reviewed setup or restore. |
| 5 | Workspace selection and enrollment | Missing: first folder is chosen silently; enrollment is not invoked. |
| 6 | Secure Orbio entry/storage | Partial: password field and SecretStorage calls work in fixtures; validation, consent and credential lifecycle are incomplete. |
| 7 | Primary/fallback selection | Partial: standalone picker excludes duplicate fallback; unverified catalog and no setup integration. |
| 8 | MCP/hooks automation | Missing from the user flow; unused CLI wrappers do not establish this feature. |
| 9 | Companion lifecycle | Missing: start/stop wrappers exist, but no controller or working lifecycle commands. |
| 10 | Health checks and first checkpoint | Incomplete/broken: no initial verification sequence; manual checkpoint uses missing script/default run. |
| 11 | Status bar and commands | Partial: all 14 commands register; nine are placeholders; status bar has no live observer. |
| 12 | Recovery/status panel | Partial: raw doctor output plus static copy; injection issue and no reviewed recovery actions. |
| 13 | Dashboard setup animation | Partial: eight steps and controls exist; lint, static fallback, reduced motion and CTA requirements fail review. |
| 14 | Tests, packaging, upgrades, rollback and failures | Partial: four basic tests and bundle activation pass; required scenario coverage and runtime packaging are absent. |
| 15 | Verified root/extension documentation | Missing for the new extension workflow. Existing CLI documentation remains. |

## Checks actually run

| Phase/check | Observed result |
|---|---|
| Current Python suite: `.venv/Scripts/python.exe -m pytest -q` | **314 passed**, two upstream deprecation warnings, 153.58 seconds. |
| Python lint: `.venv/Scripts/python.exe -m ruff check src tests scripts` | **Passed**. |
| Extension: `npm.cmd run compile` | **Passed**. |
| Extension: `npm.cmd run package` | **Passed**; esbuild JavaScript bundle only. |
| Existing extension tests using `@vscode/test-electron` and installed VS Code | **4 passed**, 844 ms; isolated profile, Cline not installed in that profile. |
| Existing VSIX contents | **44 entries**, 43,106 bytes; JS matches current bundle; icon, README and Python runtime missing. |
| Unpacked VSIX in isolated VS Code extension host | **Activated; all 14 commands registered**, host exit 0. No setup or native Cline workflow was run. |
| Review behavior fixtures | **13 observations reproduced**; includes both defects and positive checks. This is not a product acceptance-test pass count. |
| Dashboard: `npm.cmd run test:pairing` | **9 passed**. |
| Dashboard: `npm.cmd run lint` | **Failed: 3 errors**, all in the two new/changed UI files described above. |
| Dashboard: `node node_modules/typescript/bin/tsc --noEmit` | **Passed**. |
| Dashboard: `npm.cmd run build` | **Passed**; `/setup-guide` included. Vinext reports that route’s classification as unknown. |
| Dashboard component audit | Eight steps, seven initially hidden, controls labelled, active timer at completion, enabled extension URI; no reduced-motion/static fallback branch. |
| Before/after preservation comparison | **No differences** in 80 tracked review source/manifest hashes, three installed Cline/MCP file hashes, or the inspected native evidence snapshots. |

The Sites build helper was attempted first and failed because it resolved npm under the dashboard’s `node_modules/npm`, which is absent. Running the repository’s existing `npm.cmd run build` directly succeeded. This was a helper invocation issue, not a claimed product build failure.

The test framework ZIP was initially zero bytes and later measured 156,751,639 bytes. It was left alone. Both host checks used installed **VS Code 1.137.0** with disposable profiles, so the ongoing framework download did not prevent this review. No clean-machine installation claim is made.

Local evidence: [Python test log](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/python-tests.log), [existing host tests](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/extension-host.log), [packaged host result](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/packaged-host-observations.json), [behavior observations](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/behavior-observations.json), [dashboard lint](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/dashboard-lint.log), [dashboard build](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/dashboard-build-direct.log), [preservation comparison](C:/Users/USER/Downloads/VESSEL/scratch/extension-review-20260915/preservation-observations.json).

## Preserved security and recovery evidence

The review did not modify the real installed Cline bundle, its VESSEL helper, or the active MCP settings. No real key was read for inference, replaced, or sent upstream. The behavior fixtures used dummy keys and a disposable Python script. The source snapshot comparison shows no product-code edits during review.

The existing recovery canary still contains **69 events**, unchanged event digest and healthy capture. Recovery `recovery_f200a2f427c16a086e03ee6d80cd14ed` remains **succeeded**. The gateway canary still contains **24 events**, unchanged event digest and the same owner-attested healthy state. These are preserved records, not a new native success claim. Native Cline-through-gateway model switching/tool verification remains pending as before.

The 314 Python tests provide regression evidence for the existing implementation. They do not prove the new extension preserves those invariants once its currently missing features are wired up. Its eventual integration still needs explicit tests for owner authority, exact session/epoch attribution, stopped-source checkpoints, changed-input review invalidation, uncertain-operation refusal, encryption/local custody, configuration preservation and truthful native success reporting.

## Remaining acceptance validation

The brief’s terminal-free clean-Windows flow could not pass with this implementation: setup currently stops before project selection. No clean-machine onboarding, extension-managed provider validation, first checkpoint, restart/reconnect, pause/resume, removal or compatibility restoration was claimed or performed. Browser accessibility/responsive tests and live Orbio/Cline acceptance tests also remain unverified.

Only this report and ignored review artifacts were added. Compilation/build commands regenerated local output. Nothing was published or pushed, and no existing enrollment was replaced.
