"""Deterministic, change-independent repository inventory."""

import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from app.repository_intelligence.models import (
    DependencyObservation,
    InventoryCapability,
    InventoryResult,
    LanguageObservation,
    ManifestObservation,
    RepositoryWorkspace,
)
from app.repository_intelligence.workspace import _walk_entries

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".cs": "C#",
    ".php": "PHP",
}
MAX_ANALYSIS_FILE_BYTES = 2_000_000


def _stable_id(*parts: str) -> str:
    semantic_key = ":".join(parts)
    return hashlib.sha256(semantic_key.encode()).hexdigest()[:24]


def _dependency(
    ecosystem: str,
    package: str,
    source_path: str,
    detection_method: str,
    *,
    declared_specifier: str | None = None,
    resolved_version: str | None = None,
) -> DependencyObservation:
    normalized = canonicalize_name(package) if ecosystem == "pypi" else package.strip().lower()
    return DependencyObservation(
        id=f"dependency_{_stable_id(ecosystem, normalized, source_path, detection_method)}",
        ecosystem=ecosystem,
        package=normalized,
        declared_specifier=declared_specifier or None,
        resolved_version=resolved_version or None,
        source_path=source_path,
        detection_method=detection_method,
    )


def _parse_requirement(value: str, path: str) -> DependencyObservation | None:
    candidate = value.strip()
    if not candidate or candidate.startswith(("#", "-")):
        return None
    candidate = candidate.split(" #", 1)[0].strip()
    try:
        requirement = Requirement(candidate)
    except InvalidRequirement:
        return None
    specifiers = list(requirement.specifier)
    resolved_version = None
    if len(specifiers) == 1 and specifiers[0].operator == "==" and "*" not in specifiers[0].version:
        resolved_version = specifiers[0].version
    return _dependency(
        "pypi",
        requirement.name,
        path,
        "manifest",
        declared_specifier=str(requirement.specifier) or None,
        resolved_version=resolved_version,
    )


def _pyproject_dependencies(data: dict[str, Any], path: str) -> list[DependencyObservation]:
    observations = []
    project = data.get("project", {})
    values = list(project.get("dependencies", []))
    for optional in project.get("optional-dependencies", {}).values():
        values.extend(optional)
    for value in values:
        if isinstance(value, str) and (dependency := _parse_requirement(value, path)):
            observations.append(dependency)

    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for package, specifier in poetry.items():
        if package.lower() == "python":
            continue
        declared = (
            specifier if isinstance(specifier, str) else json.dumps(specifier, sort_keys=True)
        )
        observations.append(
            _dependency("pypi", package, path, "manifest", declared_specifier=declared)
        )
    return observations


def _package_json_dependencies(data: dict[str, Any], path: str) -> list[DependencyObservation]:
    observations = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for package, specifier in data.get(section, {}).items():
            observations.append(
                _dependency(
                    "npm",
                    package,
                    path,
                    "manifest",
                    declared_specifier=str(specifier),
                )
            )
    return observations


def _package_lock_dependencies(data: dict[str, Any], path: str) -> list[DependencyObservation]:
    observations = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, metadata in packages.items():
            if not key or not key.startswith("node_modules/") or not isinstance(metadata, dict):
                continue
            package = key.removeprefix("node_modules/")
            observations.append(
                _dependency(
                    "npm",
                    package,
                    path,
                    "lockfile",
                    resolved_version=metadata.get("version"),
                )
            )
    else:
        for package, metadata in data.get("dependencies", {}).items():
            if isinstance(metadata, dict):
                observations.append(
                    _dependency(
                        "npm",
                        package,
                        path,
                        "lockfile",
                        resolved_version=metadata.get("version"),
                    )
                )
    return observations


def _manifest_kind(path: str) -> str | None:
    name = Path(path).name
    if name == "pyproject.toml":
        return "pyproject"
    if name.startswith("requirements") and name.endswith(".txt"):
        return "requirements"
    if name == "package.json":
        return "package_json"
    if name == "package-lock.json":
        return "package_lock"
    return None


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class RepositoryInventoryBuilder:
    inventory_version = "1.0.0"

    def build(self, workspace: RepositoryWorkspace) -> InventoryResult:
        root = Path(workspace.root)
        language_counts: Counter[str] = Counter()
        manifests: list[ManifestObservation] = []
        dependencies: list[DependencyObservation] = []
        warnings: list[str] = []
        files_considered = 0
        files_excluded = 0
        symlinks_excluded = 0

        entries = sorted(_walk_entries(root), key=lambda item: item[0])
        for relative, entry_type, value in entries:
            if entry_type == "symlink":
                symlinks_excluded += 1
                continue
            files_considered += 1
            path = value
            language = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
            if language:
                language_counts[language] += 1
            kind = _manifest_kind(relative)
            if not kind:
                continue
            if path.stat(follow_symlinks=False).st_size > MAX_ANALYSIS_FILE_BYTES:
                files_excluded += 1
                warning = f"{relative}: manifest exceeds analysis size limit"
                warnings.append(warning)
                manifests.append(
                    ManifestObservation(path=relative, kind=kind, parsed=False, warning=warning)
                )
                continue
            try:
                raw = path.read_bytes()
                if kind == "pyproject":
                    dependencies.extend(
                        _pyproject_dependencies(tomllib.loads(raw.decode()), relative)
                    )
                elif kind == "requirements":
                    for line in raw.decode().splitlines():
                        if dependency := _parse_requirement(line, relative):
                            dependencies.append(dependency)
                elif kind == "package_json":
                    dependencies.extend(_package_json_dependencies(json.loads(raw), relative))
                else:
                    dependencies.extend(_package_lock_dependencies(json.loads(raw), relative))
                manifests.append(ManifestObservation(path=relative, kind=kind, parsed=True))
            except (
                AttributeError,
                OSError,
                TypeError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                tomllib.TOMLDecodeError,
            ) as exc:
                warning = f"{relative}: {type(exc).__name__}"
                warnings.append(warning)
                manifests.append(
                    ManifestObservation(path=relative, kind=kind, parsed=False, warning=warning)
                )

        languages = [
            LanguageObservation(language=language, file_count=count)
            for language, count in sorted(language_counts.items())
        ]
        dependencies = sorted(
            {dependency.id: dependency for dependency in dependencies}.values(),
            key=lambda item: (
                item.ecosystem,
                item.package,
                item.source_path,
                item.detection_method,
            ),
        )
        capabilities = [
            InventoryCapability(
                analyzer_id="multilanguage-static",
                analyzer_version="1.0.0",
                supported=bool(
                    language_counts["Python"]
                    or language_counts["JavaScript"]
                    or language_counts["TypeScript"]
                ),
                languages=["Python", "JavaScript", "TypeScript"],
                limitations=[
                    "Python uses AST analysis. JavaScript and TypeScript use positive-only "
                    "lexical evidence; negative results remain uncertain."
                ],
            )
        ]
        digest_payload = {
            "inventory_version": self.inventory_version,
            "repository_id": workspace.repository_id,
            "commit_sha": workspace.commit_sha,
            "workspace_digest": workspace.content_digest,
            "languages": [item.model_dump(mode="json") for item in languages],
            "manifests": [item.model_dump(mode="json") for item in manifests],
            "dependencies": [item.model_dump(mode="json") for item in dependencies],
            "capabilities": [item.model_dump(mode="json") for item in capabilities],
            "files_considered": files_considered,
            "files_excluded": files_excluded,
            "symlinks_excluded": symlinks_excluded,
            "warnings": warnings,
        }
        return InventoryResult(
            repository_id=workspace.repository_id,
            commit_sha=workspace.commit_sha,
            workspace_digest=workspace.content_digest,
            inventory_digest=_canonical_digest(digest_payload),
            languages=languages,
            manifests=manifests,
            dependencies=dependencies,
            capabilities=capabilities,
            files_considered=files_considered,
            files_excluded=files_excluded,
            symlinks_excluded=symlinks_excluded,
            warnings=warnings,
        )
