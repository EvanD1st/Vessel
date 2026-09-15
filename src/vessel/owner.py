"""Reviewed owner workflows. This interface is never exposed through agent MCP."""

from __future__ import annotations


def bounded_text(value, label, limit=8192):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise ValueError(f"{label} must be nonempty and at most {limit} bytes")
    return value.strip()


class OwnerWorkflows:
    def _save_task(self, run_id, task_id, description, status, evidence, dependencies, conn):
        from vessel.service import Blocked

        task_id = bounded_text(task_id, "Task ID", 128)
        description = bounded_text(description, "Task description", 16384)
        if status not in {"pending", "active", "blocked", "done"}:
            raise ValueError("Invalid task status")
        run = self._get("runs", run_id, conn)
        self._admit(run_id, run["execution_epoch"], conn)
        previous = self.store.get("tasks", f"{run_id}:{task_id}", conn=conn)
        if dependencies is None:
            dependencies = previous.get("dependencies", []) if previous else []
        if not isinstance(dependencies, list) or len(dependencies) > 64:
            raise ValueError("A task supports at most 64 dependencies")
        dependencies = [bounded_text(dep, "Dependency ID", 128) for dep in dependencies]
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("Duplicate task dependency")
        if status == "done" and not evidence:
            raise Blocked("Completed tasks require an observed successful operation ID")
        if evidence:
            op = self._get("operations", evidence, conn)
            if op["run_id"] != run_id or not self._successful_operation(op, conn):
                raise Blocked("Evidence does not establish observed success in this run")
        task = {
            "id": task_id,
            "run_id": run_id,
            "description": description,
            "status": status,
            "evidence": evidence,
            "dependencies": dependencies,
            "provenance": "owner_instruction",
            "verification_status": "owner_reviewed_observation" if evidence else "unverified",
        }
        tasks = {t["id"]: t for t in self.store.list("tasks", conn=conn) if t["run_id"] == run_id}
        tasks[task_id] = task
        if len(tasks) > 1000:
            raise ValueError("A run supports at most 1000 tasks")
        indegrees, dependents = {}, {key: [] for key in tasks}
        for key, item in tasks.items():
            deps = item.get("dependencies", [])
            for dep in deps:
                if dep not in tasks:
                    raise Blocked("Dependencies must name existing tasks in this run")
                dependents[dep].append(key)
                if item["status"] in {"active", "done"} and tasks[dep]["status"] != "done":
                    raise Blocked("An active or completed task has an unfinished dependency")
            indegrees[key] = len(deps)
        ready = [key for key, count in indegrees.items() if count == 0]
        visited = 0
        while ready:
            key = ready.pop()
            visited += 1
            for child in dependents[key]:
                indegrees[child] -= 1
                if indegrees[child] == 0:
                    ready.append(child)
        if visited != len(tasks):
            raise Blocked("Task dependencies contain a cycle")
        self.store.put("tasks", f"{run_id}:{task_id}", task, conn=conn)
        return task

    def review_proposal(
        self,
        proposal_id,
        decision,
        note,
        *,
        policy_revision,
        run_id=None,
        task_id=None,
        evidence=None,
        dependencies=None,
    ):
        from vessel.service import Blocked, digest

        note = bounded_text(note, "Owner review")
        if decision not in {"accept", "reject"}:
            raise ValueError("Decision must be accept or reject")
        fingerprint = digest([decision, note, policy_revision, run_id, task_id, evidence, dependencies])
        with self.store.transaction() as conn:
            self._writable(conn)
            proposal = self._get("proposals", proposal_id, conn)
            if proposal.get("decision"):
                if proposal["review_fingerprint"] != fingerprint:
                    raise Blocked("Proposal was already reviewed with different inputs")
                return proposal
            policy = self._get("control", "policy", conn)
            if policy["authority"] != "local" or policy["revision"] != policy_revision:
                raise Blocked("Current policy changed; review the proposal again")
            if decision == "accept":
                payload = proposal["payload"]
                if proposal["kind"] in {"mission", "mission_update"}:
                    policy["mission"] = bounded_text(payload.get("mission"), "Proposed mission", 65536)
                    constraints = payload.get("constraints", [])
                    if not isinstance(constraints, list) or len(constraints) > 50:
                        raise ValueError("Invalid proposed constraints")
                    # Accepting text never removes existing owner restrictions or
                    # modifies compiled capabilities, models, funding or leases.
                    additions = [bounded_text(item, "Proposed constraint", 2000) for item in constraints]
                    policy["restrictions"] = list(dict.fromkeys(policy["restrictions"] + additions))
                    if len(policy["restrictions"]) > 100:
                        raise ValueError("Too many owner restrictions")
                    policy.update(
                        revision=policy["revision"] + 1,
                        changed_at=self.clock(),
                        authorized_by=self._enrollment(conn=conn)["owner_id"],
                    )
                    self.store.put("control", "policy", policy, conn=conn)
                    self.store.put("policy_history", str(policy["revision"]), policy, conn=conn)
                    proposal["applied_policy_revision"] = policy["revision"]
                    proposal["assignment"] = "enrollment"
                else:
                    if not run_id or not task_id:
                        raise ValueError("Accepting a task requires an explicit run and task ID")
                    # Claimed completion/evidence is data. An owner must select
                    # independent observed evidence to accept a completed task.
                    claimed = payload.get("claimed_status", "pending")
                    status = "done" if claimed in {"done", "completed"} and evidence else "pending"
                    task = self._save_task(
                        run_id, task_id, payload.get("description"), status, evidence, dependencies, conn
                    )
                    proposal.update(assignment=run_id, assigned_task_id=task["id"])
            proposal.update(
                accepted=decision == "accept",
                decision=decision,
                owner_review=note,
                reviewed_by=self._enrollment(conn=conn)["owner_id"],
                reviewed_at=self.clock(),
                review_fingerprint=fingerprint,
            )
            self.store.put("proposals", proposal_id, proposal, conn=conn)
            return proposal

    def finish_run(self, run_id, outcome, note, *, evidence=None):
        from vessel.service import Blocked

        note = bounded_text(note, "Run review")
        if outcome not in {"completed", "cancelled"}:
            raise ValueError("Outcome must be completed or cancelled")
        with self.store.artifacts.hold(), self.store.transaction() as conn:
            self._writable(conn)
            run = self._get("runs", run_id, conn)
            if run["status"] in {"completed", "cancelled"}:
                if (
                    run["status"] != outcome
                    or run["finish"]["note"] != note
                    or run["finish"]["evidence"] != evidence
                ):
                    raise Blocked("Run was already finished with different inputs")
                return run
            lease = self._get("control", "lease", conn)
            policy = self._get("control", "policy", conn)
            if (
                lease["holder_run_id"] != run_id
                or lease["status"] != "paused"
                or not run.get("stop_evidence")
            ):
                raise Blocked("Stop the current native writer and record shutdown evidence first")
            if policy["authority"] != "local":
                raise Blocked("Current owner authority is unavailable")
            if outcome == "completed":
                if policy["revision"] != lease["policy_revision"]:
                    raise Blocked("Policy changed; completion requires revalidation")
                if self._get("control", "health", conn)["state"] != "healthy":
                    raise Blocked("Capture health must be healthy before completion")
                tasks = [t for t in self.store.list("tasks", conn=conn) if t["run_id"] == run_id]
                if not tasks or any(t["status"] != "done" for t in tasks):
                    raise Blocked("Complete every recorded task before finishing the run")
                if any(op["uncertain"] for op in self.operations(run_id, conn)):
                    raise Blocked("Resolve uncertain operations before completion")
                op = self._get("operations", evidence, conn) if evidence else None
                if not op or op["run_id"] != run_id or not self._successful_operation(op, conn):
                    raise Blocked("Completion requires a reviewed successful acceptance-test operation")
            run.update(
                status=outcome,
                finished_at=self.clock(),
                finish={
                    "note": note,
                    "evidence": evidence,
                    "policy_revision": policy["revision"],
                    "provenance": "owner_instruction",
                    "owner_id": self._enrollment(conn=conn)["owner_id"],
                },
            )
            lease["status"] = "closed"
            self.store.put("runs", run_id, run, conn=conn)
            self.store.put("control", "lease", lease, conn=conn)
            for credential in self.store.list("gateway_credentials", conn=conn):
                credential["revoked"] = True
                self.store.put("gateway_credentials", credential["id"], credential, conn=conn)
            conn.execute("DELETE FROM documents WHERE kind='capture_requests' AND id=?", (run_id,))
            return run

    def cancel_recovery(self, recovery_id, note):
        from vessel.service import Blocked

        note = bounded_text(note, "Cancellation reason")
        with self.store.transaction() as conn:
            self._writable(conn)
            recovery = self._get("recoveries", recovery_id, conn)
            if recovery["status"] == "cancelled":
                return recovery
            if recovery.get("destination_run_id"):
                raise Blocked("Transferred recovery cannot be cancelled; stop its current run explicitly")
            recovery.update(
                status="cancelled",
                cancelled_at=self.clock(),
                cancellation_note=note,
                cancelled_by=self._enrollment(conn=conn)["owner_id"],
            )
            self.store.put("recoveries", recovery_id, recovery, conn=conn)
            return recovery
