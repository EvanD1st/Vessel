# Environment requirements and recovery checks

Version 0.4 adds structured owner requirements alongside automatically observed
OS, architecture, companion Python version and dependency-lock digests. Declarations
live in encrypted owner state, outside the model-editable project. MCP cannot
change them. The dashboard's prepared recovery details include the resulting
findings; declarations currently use the owner CLI.

Create a small JSON file containing the requirements you actually checked:

```json
{
  "schema_version": 1,
  "client": {
    "name": "cline",
    "version": "4.1.17",
    "capabilities": ["command-hooks", "mcp"]
  },
  "python_packages": {"fastapi": "YOUR_INSTALLED_VERSION"},
  "migration_files": ["migrations/001.sql"],
  "services": [{"id": "local-api", "required": true, "available": true}],
  "databases": [{
    "id": "development-db", "required": true, "available": true,
    "expected_schema": "001", "observed_schema": "001"
  }],
  "secret_references": [{
    "id": "caea4f3d-f9e8-4a1c-8219-5fce42c71c55",
    "required": true, "available": null
  }]
}
```

The values above are examples, not verified facts about your project. Replace the
package version with the exact distribution version. Omit unused sections; empty
lists mean no declared resources in that category. Secret IDs must be opaque UUIDs.
Keep their mapping to your secret manager separately; never put a secret value,
connection string, endpoint, credential or installer command in this file.

```powershell
.\vessel.cmd declare-environment 'C:\private\requirements.json' --note 'Describe the resource checks and limitations'
.\vessel.cmd environment
.\vessel.cmd verify-environment --model MODEL_ID --context-bytes 24000 --note 'Describe the checked runtime and model capacity'
```

Run the declaration and review before saving the continuation checkpoint. Updating
a declaration increments its revision and invalidates earlier environment reviews
and prepared handovers. If it changes after a checkpoint, inspect the change and
capture a new checkpoint from the stopped writer. Updating the owner review alone
does not make an old checkpoint match a changed environment.

The inspector reads installed distribution metadata in the **companion's Python
interpreter** using [Python's metadata API](https://docs.python.org/3/library/importlib.metadata.html).
It does not verify a separate project virtual environment. Migration files use the
existing bounded artifact reader, credential exclusion rules and SHA-256 digests.
Missing, unsafe or changed files produce explicit findings. No workspace module,
installer, shell command, service probe or secret lookup runs during inspection.
Declared migration files must also be included in the checkpoint's required
artifacts. Quota omissions make the checkpoint ineligible, and a declaration
change during capture prevents commit.

Client versions/capabilities, service availability, database schema and secret
availability are **owner declarations**. They are not evidence of live Cline
compatibility or a working service. Availability accepts `true`, `false`, or
`null` for unverified. Required unavailable/unverified resources, mismatched
database schemas and missing/wrong package versions block environment approval
and recovery. Optional resource gaps are informational and remain visible in the
handover context. A generic approval note cannot suppress a structured blocker.

Input is limited to 64 KiB, 128 distributions, 128 migration files, 32 client
capabilities and 64 resources per category. Unknown fields, ambiguous normalized
package names, duplicate resource IDs, secret values in reference fields, unsafe
paths and unsupported schemas are rejected. Declaration history remains encrypted
and subject to the store's quota. Restored history cannot acquire authority by
changing these declarations.

Environment manifest version 2 is distinct from the database schema, which remains
version 1. Older checkpoints remain inspectable but need a fresh checkpoint and
environment review before continuation. This is a compatibility gate, not a database
migration. Git base/dirty-state inspection, automatic client capability detection,
live service/database probes, secret-manager resolution and cross-machine execution
remain future work. Capturing migration files is not a live database backup.
