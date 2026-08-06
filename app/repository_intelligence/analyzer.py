"""Conservative Python AST impact analyzer with explicit coverage outcomes."""

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from app.control_plane.models import (
    CallSite,
    Confidence,
    ConfidenceBasis,
    Coverage,
    DependencyMatch,
    ImpactEvidence,
    NormalizedChange,
)
from app.repository_intelligence.inventory import MAX_ANALYSIS_FILE_BYTES
from app.repository_intelligence.models import InventoryResult, RepositoryRef, RepositoryWorkspace
from app.repository_intelligence.workspace import _walk_entries


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _normalize_package(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _ecosystem_matches(dependency_ecosystem: str, target_ecosystem: str | None) -> bool:
    if not target_ecosystem:
        return True
    aliases = {
        "pypi": {"pypi", "python", "pip"},
        "npm": {"npm", "javascript", "typescript", "node"},
    }
    return target_ecosystem.lower() in aliases.get(dependency_ecosystem, {dependency_ecosystem})


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return None


def _expand_alias(value: str, aliases: dict[str, str]) -> str:
    head, *tail = value.split(".")
    expanded = aliases.get(head, head)
    return ".".join([expanded, *tail])


@dataclass
class PythonFileIndex:
    aliases: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[ast.Call, str]] = field(default_factory=list)
    string_arguments: list[tuple[ast.AST, str, str | None]] = field(default_factory=list)
    fields: list[tuple[ast.AST, str, str | None]] = field(default_factory=list)


class _PythonIndexer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.index = PythonFileIndex()

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            self.index.aliases[item.asname or item.name.split(".")[0]] = item.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for item in node.names:
                self.index.aliases[item.asname or item.name] = f"{node.module}.{item.name}"

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _dotted_name(node.value)
        if value:
            expanded = _expand_alias(value, self.index.aliases)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.index.aliases[target.id] = expanded
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted_name(node.func)
        expanded = _expand_alias(dotted, self.index.aliases) if dotted else None
        if expanded:
            self.index.calls.append((node, expanded))
        for argument in [*node.args, *[keyword.value for keyword in node.keywords]]:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                self.index.string_arguments.append((argument, argument.value, expanded))
        for keyword in node.keywords:
            if keyword.arg:
                self.index.fields.append((keyword, keyword.arg, expanded))
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.index.fields.append((key, key.value, None))
        self.generic_visit(node)


class PythonAstImpactAnalyzer:
    analyzer_id = "python-ast"
    analyzer_version = "1.0.0"

    def analyze(
        self,
        repository: RepositoryRef,
        workspace: RepositoryWorkspace,
        inventory: InventoryResult,
        change: NormalizedChange,
    ) -> ImpactEvidence:
        assessment_id = _stable_id(
            "impact", repository.id, change.id, workspace.content_digest, self.analyzer_version
        )
        dependency_matches = self._dependency_matches(inventory, change)
        call_sites: list[CallSite] = []
        parse_failures = 0
        python_files = 0
        excluded_files = inventory.files_excluded
        root = Path(workspace.root)

        for relative, entry_type, value in sorted(_walk_entries(root), key=lambda item: item[0]):
            if entry_type != "file" or value.suffix.lower() not in {".py", ".pyi"}:
                continue
            python_files += 1
            if value.stat(follow_symlinks=False).st_size > MAX_ANALYSIS_FILE_BYTES:
                excluded_files += 1
                continue
            try:
                tree = ast.parse(value.read_text(encoding="utf-8"), filename=relative)
            except (OSError, UnicodeDecodeError, SyntaxError):
                parse_failures += 1
                continue
            indexer = _PythonIndexer()
            indexer.visit(tree)
            call_sites.extend(self._match_file(relative, indexer.index, change, assessment_id))

        call_sites = sorted(
            {item.id: item for item in call_sites}.values(),
            key=lambda item: (item.path, item.start_line, item.end_line, item.id),
        )
        observed_languages = {item.language for item in inventory.languages}
        unsupported_languages = sorted(observed_languages - {"Python"})
        limitations = [
            "Dynamic dispatch, reflection, generated code, and computed strings are not resolved."
        ]
        if unsupported_languages:
            limitations.append(
                "No semantic analyzer is available for: " + ", ".join(unsupported_languages)
            )
        if parse_failures:
            limitations.append(f"{parse_failures} Python file(s) could not be parsed.")
        if excluded_files:
            limitations.append(f"{excluded_files} file(s) exceeded analysis limits.")
        if inventory.symlinks_excluded:
            limitations.append(f"{inventory.symlinks_excluded} symbolic link(s) were not analyzed.")
        if inventory.warnings:
            limitations.append(
                f"Repository inventory reported {len(inventory.warnings)} warning(s)."
            )
        coverage_excluded = excluded_files + inventory.symlinks_excluded
        full_coverage = bool(python_files) and not (
            unsupported_languages or parse_failures or coverage_excluded or inventory.warnings
        )
        coverage = Coverage(
            supported=full_coverage,
            languages=sorted(observed_languages),
            files_considered=python_files,
            files_excluded=coverage_excluded,
            parse_failures=parse_failures,
            limitations=limitations,
        )

        deterministic_findings = bool(call_sites or dependency_matches)
        if deterministic_findings:
            conclusion = "affected"
            summary = "Deterministic repository evidence matches this provider change."
            score = 1.0 if full_coverage else 0.9
        elif not python_files:
            conclusion = "unsupported"
            summary = "No supported Python source files were available for analysis."
            score = 1.0
        elif not full_coverage:
            conclusion = "uncertain"
            summary = "No match was found, but analyzer coverage is incomplete."
            score = 0.5
        else:
            conclusion = "unaffected"
            summary = "No target match was found under complete supported Python coverage."
            score = 1.0
        unresolved = limitations[1:] if not full_coverage else []
        return ImpactEvidence(
            assessment_id=assessment_id,
            conclusion=conclusion,
            summary=summary,
            dependency_matches=dependency_matches,
            call_sites=call_sites,
            coverage=coverage,
            confidence=Confidence(
                score=score,
                basis=ConfidenceBasis.deterministic,
                reasons=["Python AST and manifest/lockfile evidence only."],
                unresolved=unresolved,
            ),
        )

    def _dependency_matches(
        self, inventory: InventoryResult, change: NormalizedChange
    ) -> list[DependencyMatch]:
        targets = [
            target for target in change.targets if target.kind == "sdk_package" or target.package
        ]
        matches = []
        for dependency in inventory.dependencies:
            package = _normalize_package(dependency.package)
            matching_target = next(
                (
                    target
                    for target in targets
                    if package == _normalize_package(target.package or target.name)
                    and _ecosystem_matches(dependency.ecosystem, target.ecosystem)
                ),
                None,
            )
            if not matching_target:
                continue
            version_evidence = self._version_evidence(dependency, matching_target)
            if version_evidence is None:
                continue
            method = dependency.detection_method
            if method not in {"manifest", "lockfile", "import"}:
                method = "other"
            matches.append(
                DependencyMatch(
                    ecosystem=dependency.ecosystem,
                    package=dependency.package,
                    resolved_version=dependency.resolved_version,
                    source_path=dependency.source_path,
                    detection_method=method,
                    evidence=(
                        f"Declared provider dependency in {dependency.source_path}. "
                        f"{version_evidence}"
                    ),
                )
            )
        return matches

    def _version_evidence(self, dependency, target) -> str | None:
        affected_range = target.version_scope.affected_range if target.version_scope else None
        if not affected_range:
            return "The change does not declare an affected version range."
        if not dependency.resolved_version:
            return f"Installed version is unresolved; declared affected range is {affected_range}."
        if dependency.ecosystem != "pypi":
            return (
                f"Installed version is {dependency.resolved_version}; range {affected_range} "
                "cannot be evaluated for this ecosystem."
            )
        try:
            applies = Version(dependency.resolved_version) in SpecifierSet(affected_range)
        except (InvalidSpecifier, InvalidVersion):
            return (
                f"Installed version is {dependency.resolved_version}; range {affected_range} "
                "could not be evaluated."
            )
        if not applies:
            return None
        return (
            f"Resolved version {dependency.resolved_version} is within affected range "
            f"{affected_range}."
        )

    def _match_file(
        self,
        path: str,
        index: PythonFileIndex,
        change: NormalizedChange,
        assessment_id: str,
    ) -> list[CallSite]:
        matches = []
        for target in change.targets:
            if target.kind in {"symbol", "type"}:
                for node, symbol in index.calls:
                    if symbol == target.name or symbol.endswith(f".{target.name}"):
                        matches.append(
                            self._call_site(
                                assessment_id,
                                path,
                                node,
                                symbol,
                                target.name,
                                f"AST call resolves to changed {target.kind} {target.name}.",
                            )
                        )
            elif target.kind == "endpoint":
                for node, value, symbol in index.string_arguments:
                    if value == target.name:
                        matches.append(
                            self._call_site(
                                assessment_id,
                                path,
                                node,
                                symbol,
                                target.name,
                                f"Exact endpoint constant matches {target.name}.",
                            )
                        )
            elif target.kind == "field":
                for node, value, symbol in index.fields:
                    if value == target.name:
                        matches.append(
                            self._call_site(
                                assessment_id,
                                path,
                                node,
                                symbol,
                                target.name,
                                f"Static request field matches {target.name}.",
                            )
                        )
        return matches

    def _call_site(
        self,
        assessment_id: str,
        path: str,
        node: ast.AST,
        symbol: str | None,
        target: str,
        reason: str,
    ) -> CallSite:
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)
        return CallSite(
            id=_stable_id(
                "callsite", assessment_id, path, str(start_line), str(end_line), target, reason
            ),
            path=path,
            start_line=start_line,
            end_line=end_line,
            language="Python",
            symbol=symbol,
            target=target,
            detection_method="ast",
            reason=reason,
            confidence=Confidence(
                score=1.0,
                basis=ConfidenceBasis.deterministic,
                reasons=["Parsed from a static Python AST node."],
            ),
        )
