 # tools/prune_docs_to_legacy.py
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable
import os

PROTECTED_EXACT = {
    Path("docs/deployment.md"),
    Path("docs/operational_assumptions.md"),
    Path("docs/scanner_expectations.md"),
    Path("docs/docker-data-persistence.md"),
    Path("docs/dev-environment.md"),
}
PROTECTED_PREFIXES = (
    Path("docs/fixtures"),
    Path("docs/ingest"),
    Path("docs/legacy"),
)

MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
# Reasonable plain-path references in README/docs text.
PLAIN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:README\.md|(?:\.\./|\./)?docs/[A-Za-z0-9._/-]+\.md|(?:\.\./|\./)[A-Za-z0-9._/-]+\.md)"
)


class PruneError(Exception):
    pass


def run(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=check,
        )
    except FileNotFoundError as e:
        raise PruneError(f"Required command not found: {cmd[0]}") from e


def repo_root() -> Path:
    cp = run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd(), check=False)
    if cp.returncode != 0:
        raise PruneError("Not a git repository or git is unavailable.")
    root = Path(cp.stdout.strip())
    if not root.exists():
        raise PruneError("Unable to determine repository root.")
    return root


def ensure_clean_worktree(root: Path) -> None:
    cp = run(["git", "status", "--porcelain"], cwd=root, check=False)
    if cp.returncode != 0:
        raise PruneError("Unable to read git working tree status.")
    if cp.stdout.strip():
        raise PruneError("Working tree is dirty. Commit/stash changes before running prune.")


def is_protected(rel_path: Path) -> bool:
    rel = rel_path.as_posix()
    if rel_path in PROTECTED_EXACT:
        return True
    return any(rel.startswith(prefix.as_posix() + "/") for prefix in PROTECTED_PREFIXES)


def markdown_sources(root: Path) -> list[Path]:
    paths: list[Path] = []
    readme = root / "README.md"
    if readme.exists():
        paths.append(readme)
    docs_root = root / "docs"
    if docs_root.exists():
        paths.extend(sorted(docs_root.rglob("*.md")))
    return paths


def archive_candidates(root: Path) -> list[Path]:
    docs_root = root / "docs"
    if not docs_root.exists():
        return []
    out: list[Path] = []
    for p in sorted(docs_root.rglob("*.md")):
        rel = p.relative_to(root)
        if is_protected(rel):
            continue
        out.append(p)
    return out


def strip_comments_and_fences(text: str) -> str:
    # Remove HTML comments and fenced code blocks to reduce false path matches.
    no_comments = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    no_fences = re.sub(r"```.*?```", "", no_comments, flags=re.DOTALL)
    return no_fences


def split_target_suffix(url: str) -> tuple[str, str]:
    for idx, ch in enumerate(url):
        if ch in "?#":
            return url[:idx], url[idx:]
    return url, ""


def normalize_path_separators(path_text: str) -> str:
    return path_text.replace("\\", "/")


def is_external(url: str) -> bool:
    low = url.lower()
    return (
        low.startswith("http://")
        or low.startswith("https://")
        or low.startswith("mailto:")
        or low.startswith("tel:")
        or low.startswith("#")
        or low.startswith("data:")
    )


def resolve_ref_to_repo_rel(
    source: Path,
    ref_text: str,
    root: Path,
    *,
    require_exists: bool,
) -> Path | None:
    root_resolved = root.resolve()
    ref = ref_text.strip().strip("<>").strip()
    if not ref:
        return None
    path_part, _ = split_target_suffix(ref)
    path_part = normalize_path_separators(path_part)
    if not path_part or is_external(path_part):
        return None

    if not path_part.lower().endswith(".md"):
        return None

    if path_part.startswith("/"):
        candidate = root_resolved / path_part.lstrip("/")
    else:
        candidate = source.parent / path_part
    candidate = candidate.resolve()

    try:
        candidate_rel = candidate.relative_to(root_resolved)
    except ValueError:
        return None

    if require_exists and (not candidate.exists() or not candidate.is_file()):
        return None

    return candidate_rel


def find_referenced_docs(sources: Iterable[Path], root: Path) -> set[Path]:
    referenced: set[Path] = set()
    for src in sources:
        text = src.read_text(encoding="utf-8")
        scan_text = strip_comments_and_fences(text)

        for target in MD_LINK_RE.findall(scan_text):
            # Handle optional title in markdown targets: (path "title")
            first = target.strip().split(maxsplit=1)[0]
            resolved = resolve_ref_to_repo_rel(src, first, root, require_exists=True)
            if resolved is not None:
                referenced.add(root / resolved)

        for ref in PLAIN_PATH_RE.findall(scan_text):
            resolved = resolve_ref_to_repo_rel(src, ref, root, require_exists=True)
            if resolved is not None:
                referenced.add(root / resolved)

    return referenced


def update_references_in_file(
    src: Path,
    root: Path,
    move_map_rel: dict[Path, Path],
) -> list[tuple[str, str]]:
    original = src.read_text(encoding="utf-8")
    text = original
    replacements: list[tuple[str, str]] = []

    def replace_md_link(match: re.Match[str]) -> str:
        target_raw = match.group(1)
        target_body = target_raw.strip()
        parts = target_body.split(maxsplit=1)
        url_part = parts[0] if parts else ""
        tail = " " + parts[1] if len(parts) == 2 else ""

        resolved_rel = resolve_ref_to_repo_rel(src, url_part, root, require_exists=False)
        if resolved_rel is None or resolved_rel not in move_map_rel:
            return match.group(0)

        _, suffix = split_target_suffix(url_part)
        new_abs = root / move_map_rel[resolved_rel]
        new_url = os.path.relpath(str(new_abs), str(src.parent)).replace("\\", "/") + suffix
        new_target = f"{new_url}{tail}".strip()
        replacements.append((target_raw, new_target))
        return match.group(0).replace(target_raw, new_target)

    text = MD_LINK_RE.sub(replace_md_link, text)

    # Update plain path references when they exactly reference moved docs.
    for old_rel_root_path, new_rel_root_path in move_map_rel.items():
        old_rel_root = old_rel_root_path.as_posix()
        new_rel_root = new_rel_root_path.as_posix()
        if old_rel_root in text:
            text = text.replace(old_rel_root, new_rel_root)
            replacements.append((old_rel_root, new_rel_root))

    if text == original:
        return []

    src.write_text(text, encoding="utf-8")
    return replacements


def build_move_plan(root: Path, to_move: Iterable[Path]) -> list[tuple[Path, Path]]:
    plan: list[tuple[Path, Path]] = []
    seen_destinations: set[Path] = set()

    for old_abs in to_move:
        old_rel = old_abs.relative_to(root)
        dest_rel = Path("docs/legacy") / old_rel.relative_to("docs")

        if not old_abs.exists() or not old_abs.is_file():
            raise PruneError(f"Preflight failed: source file missing: {old_rel.as_posix()}")
        if dest_rel in seen_destinations:
            raise PruneError(f"Preflight failed: multiple sources map to destination: {dest_rel.as_posix()}")
        if (root / dest_rel).exists():
            raise PruneError(f"Preflight failed: destination already exists: {dest_rel.as_posix()}")

        seen_destinations.add(dest_rel)
        plan.append((old_rel, dest_rel))

    return plan


def main() -> int:
    try:
        root = repo_root()
        ensure_clean_worktree(root)

        sources_before = markdown_sources(root)
        referenced = find_referenced_docs(sources_before, root)

        candidates = archive_candidates(root)
        to_move: list[Path] = []
        kept_referenced: list[Path] = []

        for doc in candidates:
            rel = doc.relative_to(root)
            if doc in referenced:
                kept_referenced.append(rel)
                continue
            to_move.append(doc)

        move_plan = build_move_plan(root, to_move)
        move_map_rel: dict[Path, Path] = {}
        moved_pairs: list[tuple[Path, Path]] = []

        for old_rel, dest_rel in move_plan:
            new_abs = root / dest_rel
            new_abs.parent.mkdir(parents=True, exist_ok=True)
            cp = run(["git", "mv", old_rel.as_posix(), dest_rel.as_posix()], cwd=root, check=False)
            if cp.returncode != 0:
                raise PruneError(f"git mv failed for {old_rel} -> {dest_rel}: {cp.stderr.strip()}")
            move_map_rel[old_rel] = dest_rel
            moved_pairs.append((old_rel, dest_rel))

        links_updated: list[tuple[Path, str, str]] = []
        if move_map_rel:
            sources_after = markdown_sources(root)
            for src in sources_after:
                replacements = update_references_in_file(src, root, move_map_rel)
                if replacements:
                    src_rel = src.relative_to(root)
                    for old_ref, new_ref in replacements:
                        links_updated.append((src_rel, old_ref, new_ref))

        # Required verification step.
        run(["python", "-m", "compileall", "."], cwd=root, check=True)

        print("Kept files (referenced):")
        if kept_referenced:
            for p in sorted(kept_referenced):
                print(f"- {p.as_posix()}")
        else:
            print("- (none)")

        print("\nFiles moved (unreferenced candidates):")
        if moved_pairs:
            for old_rel, new_rel in moved_pairs:
                print(f"- {old_rel.as_posix()} -> {new_rel.as_posix()}")
        else:
            print("- (none)")

        print("\nLinks updated (old -> new):")
        if links_updated:
            for src_rel, old_ref, new_ref in sorted(links_updated):
                print(f"- {src_rel.as_posix()}: {old_ref} -> {new_ref}")
        else:
            print("- (none)")

        return 0
    except PruneError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        msg = stderr or str(e)
        print(f"ERROR: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())