"""Pinned draft norms and a deliberately offline, default-deny research policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class GovernanceError(RuntimeError):
    """A governance condition cannot be confirmed; do not execute."""


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise GovernanceError("Only finite JSON values are accepted") from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Policy:
    def __init__(self, repository: Path):
        self.repository = Path(repository).resolve()
        self.manifest_path = self.repository / "governance/manifest.json"
        self.settings_path = self.repository / "governance/research-policy.json"
        self._manifest_bytes = self.manifest_path.read_bytes()
        self._settings_bytes = self.settings_path.read_bytes()
        self.manifest = json.loads(self._manifest_bytes)
        self.settings = json.loads(self._settings_bytes)
        self.norm_revision = sha256(self._manifest_bytes)
        self.policy_revision = sha256(self._settings_bytes)
        self._object_digest = sha256(canonical([self.manifest, self.settings]).encode())
        self.assert_integrity()
        if self.settings["mode"] != "research" or self.manifest["status"] != "draft":
            raise GovernanceError(
                "This release supports offline draft research only; production is unavailable"
            )
        if self.settings["network"] or self.settings["shell"] or self.settings["external_delegation"]:
            raise GovernanceError("Network, shell and external delegation must be disabled")
        if not isinstance(self.settings.get("purpose"), str) or not self.settings["purpose"].strip():
            raise GovernanceError("An explicit research purpose is required")
        self.tools = {spec["name"]: spec for spec in self.settings["tools"]}
        if len(self.tools) != len(self.settings["tools"]):
            raise GovernanceError("Duplicate tool names")
        for spec in self.tools.values():
            if (
                spec["kind"] != "mock"
                or type(spec["cost_units"]) is not int
                or spec["cost_units"] < 1
                or type(spec["timeout_seconds"]) not in (int, float)
                or not 0 < spec["timeout_seconds"] <= 10
            ):
                raise GovernanceError("Only bounded, explicitly registered mock tools are accepted")
        for name in ("max_operations", "max_tasks", "max_task_seconds", "max_approval_seconds", "max_depth"):
            if type(self.settings[name]) is not int or self.settings[name] <= 0:
                raise GovernanceError(f"Missing positive bound: {name}")

    def assert_integrity(self) -> None:
        try:
            if self.manifest_path.read_bytes() != self._manifest_bytes:
                raise GovernanceError("Norm manifest changed; approvals are invalid")
            if self.settings_path.read_bytes() != self._settings_bytes:
                raise GovernanceError("Runtime policy changed; approvals are invalid")
            if sha256(canonical([self.manifest, self.settings]).encode()) != self._object_digest:
                raise GovernanceError("Loaded policy was modified")
            for source in self.manifest["sources"]:
                path = (self.repository / source["path"]).resolve()
                if not path.is_relative_to(self.repository):
                    raise GovernanceError("Source path escaped repository")
                if sha256(path.read_bytes()) != source["sha256"]:
                    raise GovernanceError("Pinned constitution or operating rules changed")
            if len(self.manifest["sources"]) != 2:
                raise GovernanceError("Both layers must be pinned")
            if {s["path"] for s in self.manifest["sources"]} != {
                "governance/sources/CONSTITUTION.md",
                "governance/sources/OPERATING_RULES.md",
            }:
                raise GovernanceError("Distinct constitution and operating rules sources are required")
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise GovernanceError("Cannot verify governance configuration") from exc

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> str:
        self.assert_integrity()
        if name not in self.tools or type(arguments) is not dict:
            raise GovernanceError("Unknown tool or invalid arguments")
        schema = self.tools[name]["arguments"]
        if set(arguments) != set(schema):
            raise GovernanceError("Unexpected or missing argument")
        for key, kind in schema.items():
            value = arguments[key]
            if kind == "string" and (type(value) is not str or len(value) > 2048):
                raise GovernanceError("String argument exceeds research bounds")
            if kind == "integer" and (type(value) is not int or abs(value) > 10000):
                raise GovernanceError("Integer argument exceeds research bounds")
            if kind not in ("string", "integer"):
                raise GovernanceError("Unsupported argument schema")
        payload = canonical(arguments)
        if len(payload.encode()) > 8192:
            raise GovernanceError("Proposal exceeds size bound")
        return payload

    def instructions(self) -> str:
        self.assert_integrity()
        sections = [
            "Human x Agent draft research configuration. These documents are not enacted law.",
            "Purpose: " + self.settings["purpose"],
            "Only propose mock actions; owner decisions and execution belong to the host.",
        ]
        for source in self.manifest["sources"]:
            sections.append(source["path"] + "\n" + (self.repository / source["path"]).read_text())
        return "\n\n".join(sections)
