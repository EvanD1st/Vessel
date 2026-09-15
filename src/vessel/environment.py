"""Observed package/file evidence and explicit owner resource declarations.

No workspace programs, service probes, secret resolution or installers run here.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
import uuid

from vessel.storage import canonical_json

MAX_REQUIREMENTS_BYTES = 65536
SECTIONS = {
    "schema_version",
    "client",
    "python_packages",
    "migration_files",
    "services",
    "databases",
    "secret_references",
}


def _object(value, allowed, required):
    if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
        raise ValueError("Environment declaration has missing or unsupported fields")


def _label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+/-]{0,95}", value):
        raise ValueError("Use a bounded identifier/version, not a URL, command or secret value")
    return value


def normalize(value):
    """Validate owner input before it enters the private store. Unknown fields fail closed."""
    from vessel.artifacts import _exclusion, _relative

    _object(value, SECTIONS, {"schema_version"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported environment requirements schema")
    if len(canonical_json(value)) > MAX_REQUIREMENTS_BYTES:
        raise ValueError("Environment requirements exceed 64 KiB")
    result = {"schema_version": 1, "client": None}
    client = value.get("client")
    if client is not None:
        _object(client, {"name", "version", "capabilities"}, {"name", "version", "capabilities"})
        capabilities = client["capabilities"]
        if not isinstance(capabilities, list) or len(capabilities) > 32:
            raise ValueError("Declare at most 32 client capabilities")
        result["client"] = {
            "name": _label(client["name"]),
            "version": _label(client["version"]),
            "capabilities": sorted({_label(item) for item in capabilities}),
        }
    packages = value.get("python_packages", {})
    if not isinstance(packages, dict) or len(packages) > 128:
        raise ValueError("Declare at most 128 Python distributions")
    result["python_packages"] = {}
    for name, version in packages.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", name):
            raise ValueError("Invalid Python distribution name")
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in result["python_packages"]:
            raise ValueError("Duplicate normalized Python distribution")
        result["python_packages"][name] = _label(version)
    migrations = value.get("migration_files", [])
    if not isinstance(migrations, list) or len(migrations) > 128:
        raise ValueError("Declare at most 128 migration files")
    checked = []
    for path in migrations:
        relative = _relative(path)
        if _exclusion(relative):
            raise ValueError("Migration file is excluded by artifact policy")
        checked.append(relative)
    if len(set(checked)) != len(checked):
        raise ValueError("Duplicate migration file")
    result["migration_files"] = sorted(checked)
    for section in ("services", "databases", "secret_references"):
        items = value.get(section, [])
        if not isinstance(items, list) or len(items) > 64:
            raise ValueError("Declare at most 64 resources per category")
        result[section], seen = [], set()
        for item in items:
            fields = {"id", "required", "available"}
            if section == "databases":
                fields |= {"expected_schema", "observed_schema"}
            _object(item, fields, fields)
            identity = item["id"]
            if section == "secret_references":
                try:
                    if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
                        raise ValueError
                except (ValueError, AttributeError):
                    raise ValueError("Secret references must be opaque UUIDs, never secret values") from None
            else:
                _label(identity)
            if identity in seen:
                raise ValueError("Duplicate resource identifier")
            seen.add(identity)
            if type(item["required"]) is not bool or (
                item["available"] is not None and type(item["available"]) is not bool
            ):
                raise ValueError("Required must be boolean; availability must be boolean or null")
            record = {"id": identity, "required": item["required"], "available": item["available"]}
            if section == "databases":
                record["expected_schema"] = _label(item["expected_schema"])
                record["observed_schema"] = (
                    None if item["observed_schema"] is None else _label(item["observed_schema"])
                )
            result[section].append(record)
        result[section].sort(key=lambda item: item["id"])
    return result


def declare(service, requirements, note):
    if not isinstance(note, str) or not note.strip() or len(note.encode()) > 4096:
        raise ValueError("Record a bounded owner note describing the resource checks")
    requirements = normalize(requirements)
    with service.store.transaction() as conn:
        service._writable(conn)
        service._enrollment(conn=conn)
        previous = service.store.get("control", "environment_requirements", conn=conn)
        record = {
            "revision": previous["revision"] + 1 if previous else 1,
            "requirements": requirements,
            "provenance": "owner_declared",
            "evidence": note,
            "at": service.clock(),
        }
        service.store.put("control", "environment_requirements", record, conn=conn)
        service.store.put("environment_history", str(record["revision"]), record, conn=conn)
        return record


def inspect_requirements(artifacts):
    record = artifacts.store.get("control", "environment_requirements")
    requirements = normalize(record["requirements"] if record else {"schema_version": 1})
    packages, migrations, errors = {}, {}, []
    for name, expected in sorted(requirements["python_packages"].items()):
        try:
            observed = importlib.metadata.version(name)
            if not isinstance(observed, str) or len(observed) > 128:
                raise ValueError("Unbounded package version")
            packages[name] = {"expected": expected, "observed": observed}
        except importlib.metadata.PackageNotFoundError:
            packages[name] = {"expected": expected, "observed": None}
        except (OSError, ValueError):
            errors.append(f"python_package_inspection_failed:{name}")
    for relative in requirements["migration_files"]:
        try:
            content, _ = artifacts._read(relative)
            migrations[relative] = hashlib.sha256(content).hexdigest()
        except (OSError, ValueError):
            errors.append(f"migration_unavailable_or_unsafe:{relative}")
    return {
        "requirements": requirements,
        "requirements_revision": record["revision"] if record else 0,
        "requirements_provenance": "owner_declared" if record else "not_declared",
        "python_packages": packages,
        "package_inspection_scope": "the VESSEL companion Python interpreter; no workspace code imported",
        "migration_digests": migrations,
        "requirement_errors": errors,
        "availability_provenance": "owner_attested; no live service, database or credential probe",
    }


def findings(environment):
    """Specific requirements blocking continuation, with no credential values."""
    result = []

    def add(code, field, severity, repair):
        result.append({"code": code, "field": field, "severity": severity, "repair": repair})

    for name, package in sorted(environment.get("python_packages", {}).items()):
        if package["observed"] != package["expected"]:
            add(
                "python_dependency_mismatch",
                name,
                "repair_required",
                "Install/verify the declared version in the companion interpreter, then review again.",
            )
    for error in environment.get("requirement_errors", []):
        add(
            "environment_inspection_failed",
            error,
            "blocking",
            "Restore the approved file or resolve the inspection error, then review again.",
        )
    for section in ("services", "databases", "secret_references"):
        for item in environment.get("requirements", {}).get(section, []):
            if item["available"] is not True:
                add(
                    "resource_unavailable_or_unverified",
                    f"{section}:{item['id']}",
                    "blocking" if item["required"] else "informational",
                    "Check availability outside VESSEL and update the owner declaration.",
                )
            if section == "databases" and item["expected_schema"] != item["observed_schema"]:
                add(
                    "database_schema_mismatch",
                    item["id"],
                    "blocking" if item["required"] else "informational",
                    "Review and reconcile database schema/migrations; a file snapshot cannot repair a live database.",
                )
    return result


def compare(source, destination):
    result = findings(destination)
    for field in sorted(set(source) | set(destination)):
        if source.get(field) == destination.get(field):
            continue
        result.append(
            {
                "code": "environment_changed",
                "field": field,
                "severity": "blocking"
                if field in {"schema_version", "os", "architecture"}
                else "repair_required",
                "repair": "Review the changed environment and capture a new checkpoint before continuation.",
            }
        )
    return result
