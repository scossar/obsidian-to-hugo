"""Conservative Markdown export; uses Hugo itself to render its archetype."""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import tomlkit
import yaml

IMAGES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".avif",
    ".bmp",
    ".ico",
    ".tif",
    ".tiff",
}


def external(target):
    return bool(urlsplit(target).scheme) or target.startswith("//")


def strip_frontmatter(text):
    lines = text.lstrip("\ufeff").splitlines(keepends=True)
    if lines and lines[0].strip() in {"---", "+++"}:
        marker = lines[0].strip()
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == marker or (marker == "---" and line.strip() == "..."):
                return "".join(lines[i + 1 :]), i + 1
        raise ValueError("Unterminated note frontmatter")
    return "".join(lines), 0


def note_metadata(text):
    """Read only frontmatter; return validated overrides for Hugo."""
    _, offset = strip_frontmatter(text)
    if not offset:
        return {}
    lines = text.lstrip("\ufeff").splitlines(keepends=True)
    raw = "".join(lines[1 : offset - 1])
    try:
        metadata = (
            tomllib.loads(raw) if lines[0].strip() == "+++" else yaml.safe_load(raw)
        )
    except (ValueError, yaml.YAMLError) as error:
        raise ValueError(f"Invalid note frontmatter: {error}") from error
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("Note frontmatter must contain a mapping of properties")
    overrides = {}
    created = metadata.get("created_at")
    if created is not None:
        try:
            if isinstance(created, datetime):
                created = created.date()
            elif isinstance(created, str):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", created):
                    created = date.fromisoformat(created)
                elif re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]", created):
                    created = datetime.fromisoformat(created).date()
                else:
                    raise ValueError("Expected ISO date or timestamp")
            if not isinstance(created, date):
                raise ValueError("Expected a date")
        except ValueError as error:
            raise ValueError(
                "created_at must be a valid YYYY-MM-DD date or ISO timestamp"
            ) from error
        overrides["date"] = created.isoformat()
    tags = metadata.get("tags")
    if tags is not None:
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be a list of strings or a single string")
        overrides["tags"] = tags
    return overrides


def apply_metadata(generated, overrides):
    if not overrides:
        return generated
    body, offset = strip_frontmatter(generated)
    lines = generated.lstrip("\ufeff").splitlines(keepends=True)
    if not offset or lines[0].strip() != "+++":
        raise ValueError(
            "Metadata overrides require TOML (+++) Hugo archetype frontmatter"
        )
    document = tomlkit.parse("".join(lines[1 : offset - 1]))
    for key, value in overrides.items():
        document[key] = tomlkit.string(value) if isinstance(value, str) else value
    return "+++\n" + tomlkit.dumps(document).rstrip("\n") + "\n+++\n" + body


def protected(text):
    """Mask code and comments without changing source offsets."""
    mask = list(text)
    fence = None
    offset = 0
    for line in text.splitlines(keepends=True):
        m = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        hide = fence is not None or m is not None or line.startswith(("    ", "\t"))
        if fence:
            if re.match(
                r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$",
                line,
            ):
                fence = None
        elif m:
            fence = m[1]
        if hide:
            mask[offset : offset + len(line)] = [
                "\n" if c == "\n" else " " for c in line
            ]
        offset += len(line)
    masked = "".join(mask)
    for m in re.finditer(
        r"<!--.*?(?:-->|\Z)|(`+)(?!`)(.*?)(?<!`)\1(?!`)", masked, re.S
    ):
        mask[m.start() : m.end()] = ["\n" if c == "\n" else " " for c in m[0]]
    return "".join(mask)


def closing(text, start, left, right):
    depth = 0
    i = start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == left:
            depth += 1
        elif text[i] == right:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def destination(value):
    value = value.strip()
    if value.startswith("<") and ">" in value:
        end = value.index(">")
        return value[1:end], value[end + 1 :]
    m = re.match(r"""(.*?)(\s+["'].*["'])\s*$""", value, re.S)
    return (m[1], m[2]) if m else (value, "")


def normalize(label):
    return " ".join(label.split()).casefold()


class Export:
    def __init__(self, vault, site, note):
        self.vault, self.site, self.note = vault, site, note
        self.copies = {}
        self.warnings = []

    def warn(self, line, message):
        self.warnings.append(f"{self.note}:{line}: {message}")

    def image(self, target):
        if external(target):
            return target
        decoded = unquote(target)
        roots = [(self.vault / name).resolve() for name in ("assets", "website_assets")]
        explicit = [
            (self.note.parent / decoded).resolve(),
            (self.vault / decoded.lstrip("/")).resolve(),
        ]
        candidates = {
            p
            for p in explicit
            if p.is_file() and any(p.is_relative_to(r) for r in roots)
        }
        if not candidates:
            for root in roots:
                if root.is_dir():
                    candidates.update(
                        p.resolve()
                        for p in root.rglob("*")
                        if p.is_file()
                        and p.name == Path(decoded).name
                        and p.resolve().is_relative_to(root)
                    )
        if not candidates:
            raise ValueError(f"Image not found in assets or website_assets: {target}")
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous image {target}; use its vault-relative path")
        source = candidates.pop()
        dest = self.site / "static" / "images" / source.name
        if not dest.resolve().is_relative_to(self.site):
            raise ValueError(f"Image destination escapes Hugo site: {dest}")
        other = self.copies.get(dest)
        if other and not filecmp.cmp(source, other, shallow=False):
            raise ValueError(f"Different images share the filename {source.name}")
        if dest.exists() and (
            not dest.is_file() or not filecmp.cmp(source, dest, shallow=False)
        ):
            raise ValueError(f"Refusing to overwrite different image: {dest}")
        self.copies[dest] = source
        return "/images/" + quote(source.name, safe="-._~")

    def convert(self, original):
        text, offset = strip_frontmatter(original)
        scan = protected(text)
        refs = {}
        for m in re.finditer(r"^ {0,3}\[([^\]\n]+)\]:[ \t]*(.+)$", scan, re.M):
            refs.setdefault(normalize(m[1]), destination(text[m.start(2) : m.end(2)]))
            target, _ = refs[normalize(m[1])]
            if not external(target):
                self.warn(
                    offset + text.count("\n", 0, m.start()) + 1,
                    f"Internal reference definition left unchanged: {target}",
                )
        edits = []
        i = 0
        while i < len(scan):
            if scan[i] == "\\":
                i += 2
                continue
            embed = scan.startswith("![", i)
            start = i + 1 if embed else i
            if scan[start : start + 2] == "[[":
                end = scan.find("]]", start + 2)
                if end == -1:
                    i += 1
                    continue
                target, sep, alias = text[start + 2 : end].partition("|")
                line = offset + text.count("\n", 0, i) + 1
                if embed and Path(unquote(target)).suffix.lower() in IMAGES:
                    alt = (
                        alias
                        if sep and not re.fullmatch(r"\d+(?:x\d+)?", alias)
                        else Path(unquote(target)).stem
                    )
                    alt = (
                        alt.replace("\\", "\\\\")
                        .replace("[", "\\[")
                        .replace("]", "\\]")
                    )
                    edits.append((i, end + 2, f"![{alt}]({self.image(target)})"))
                    if sep and re.fullmatch(r"\d+(?:x\d+)?", alias):
                        self.warn(line, f"Obsidian image dimensions omitted: {alias}")
                else:
                    self.warn(
                        line, f"Internal link/embed left unchanged: {text[i : end + 2]}"
                    )
                i = end + 2
                continue
            if scan[start : start + 1] != "[":
                i += 1
                continue
            end = closing(scan, start, "[", "]")
            if end is None:
                i += 1
                continue
            label = text[start + 1 : end]
            after = end + 1
            target = None
            suffix = ""
            if scan[after : after + 1] == "(":
                finish = closing(scan, after, "(", ")")
                if finish is not None:
                    target, suffix = destination(text[after + 1 : finish])
                    after = finish + 1
            elif scan[after : after + 1] != ":":
                ref = label
                if scan[after : after + 1] == "[":
                    finish = scan.find("]", after + 1)
                    if finish != -1:
                        ref = text[after + 1 : finish] or label
                        after = finish + 1
                if normalize(ref) in refs:
                    target, suffix = refs[normalize(ref)]
            if target is not None:
                if embed:
                    if not external(target):
                        edits.append(
                            (i, after, f"![{label}]({self.image(target)}{suffix})")
                        )
                elif not external(target):
                    self.warn(
                        offset + text.count("\n", 0, i) + 1,
                        f"Internal link left unchanged: {target}",
                    )
                # Inspect a link's label too: it may contain a linked image.
                i = after if embed else start + 1
            else:
                i += 1
        for start, end, value in reversed(edits):
            text = text[:start] + value + text[end:]
        return text


def relative(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Expected a relative path without '..': {value}")
    return path


def run(args):
    vault = args.vault.expanduser().resolve()
    site = args.hugo_site.expanduser().resolve()
    note = args.note.expanduser()
    note = (vault / note).resolve() if not note.is_absolute() else note.resolve()
    if not note.is_relative_to(vault) or note.suffix.lower() != ".md":
        raise ValueError("Note must be a Markdown file inside the vault")
    if not (site / "archetypes/default.md").is_file():
        raise ValueError(f"Missing Hugo archetype: {site / 'archetypes/default.md'}")
    slug = re.sub(
        r"[^\w-]+", "-", unicodedata.normalize("NFKC", note.stem).lower()
    ).strip("-_")
    filename = args.filename or f"{slug}.md"
    if not slug or Path(filename).name != filename or not filename.endswith(".md"):
        raise ValueError("Provide a valid Markdown --filename, without directories")
    content = (site / relative(args.content_dir)).resolve()
    dest_rel = relative(args.directory) / filename
    dest = (content / dest_rel).resolve()
    if not content.is_relative_to(site) or not dest.is_relative_to(content):
        raise ValueError("Destination must stay inside the Hugo content directory")
    if dest.exists():
        raise ValueError(f"Refusing to overwrite existing post: {dest}")
    export = Export(vault, site, note)
    original = note.read_text(encoding="utf-8")
    overrides = note_metadata(original)
    body = export.convert(original)
    for warning in export.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"{'Would create' if args.dry_run else 'Creating'}: {dest}")
    for key, value in overrides.items():
        print(f"Frontmatter: {key} = {json.dumps(value, ensure_ascii=False)}")
    for target, source in export.copies.items():
        print(f"{'Reuse' if target.exists() else 'Copy'}: {source} -> {target}")
    if args.dry_run:
        return
    # A minimal temporary site renders the actual default archetype with Hugo,
    # avoiding theme/build side effects and leaving the destination untouched on failure.
    with tempfile.TemporaryDirectory(prefix="obsidian-to-hugo-") as directory:
        staging = Path(directory)
        (staging / "hugo.toml").write_text("", encoding="utf-8")
        (staging / "archetypes").mkdir()
        (staging / "content").mkdir()
        shutil.copy2(site / "archetypes/default.md", staging / "archetypes/default.md")
        subprocess.run(
            [
                "hugo",
                "new",
                "content",
                dest_rel.as_posix(),
                "--kind",
                "default",
                "--source",
                str(staging),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = (staging / "content" / dest_rel).read_text(encoding="utf-8")
    generated = apply_metadata(generated, overrides)
    created = []
    try:
        for target, source in export.copies.items():
            if target.exists():
                if not filecmp.cmp(source, target, shallow=False):
                    raise ValueError(f"Image changed during export: {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                created.append(target)
                with source.open("rb") as image:
                    shutil.copyfileobj(image, output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("x", encoding="utf-8") as output:
            created.append(dest)
            output.write(generated.rstrip() + "\n\n" + body.lstrip("\n"))
    except BaseException:
        for path in reversed(created):
            path.unlink()
        raise
    print(f"Created: {dest} ({len(export.warnings)} warning(s))")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "note",
        type=Path,
        help="Note path, absolute or relative to the vault (include .md)",
    )
    parser.add_argument(
        "--directory",
        default="notes",
        help="Destination section under content (default: notes)",
    )
    parser.add_argument("--vault", type=Path, default=Path.home() / "obsidian_vault")
    parser.add_argument("--hugo-site", type=Path, default=Path.home() / "zalgorithm")
    parser.add_argument(
        "--content-dir", default="content", help="Content directory relative to site"
    )
    parser.add_argument(
        "--filename", help="Override generated lowercase, hyphenated filename"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing files",
    )
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Error: {error}\n{getattr(error, 'stderr', '') or ''}")


if __name__ == "__main__":
    main()
