#!/usr/bin/env python3
"""
flatten.py — Flatten a directory of scraped markdown files into a single RAG document.

Usage:
    uv run python flatten.py <INPUT_DIR> [OPTIONS]

Options:
    --output FILE       Output filename (default: <domain>_rag.md next to INPUT_DIR)
    --no-dedup          Disable paragraph-level deduplication (default: dedup ON)
    --min-words INT     Min words for a paragraph to enter the seen-set (default: 5)
    --verbose           Show per-file dedup stats
"""

import hashlib
import re
import sys
from pathlib import Path

import click


SEPARATOR = "\n\n---\n\n"


def collect_markdown_files(input_dir: Path) -> list[Path]:
    """Recursively collect all .md files, sorted for deterministic order."""
    return sorted(input_dir.rglob("*.md"))


def extract_metadata(content: str) -> tuple[dict, str]:
    """Parse YAML front-matter (--- ... ---) and return (metadata, body)."""
    metadata: dict = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    metadata[k.strip()] = v.strip()
            body = parts[2].lstrip("\n")
    return metadata, body


def para_hash(text: str) -> str:
    """Stable hash of a paragraph after normalising whitespace."""
    normalised = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()


def deduplicate_body(body: str, seen: set[str], min_words: int) -> tuple[str, int, int]:
    """
    Return (deduplicated_body, kept_count, dropped_count).

    Paragraphs already in `seen` are removed. Any paragraph with at least
    `min_words` words is added to `seen` so it won't appear in later pages.
    Short paragraphs (headings, stray punctuation) are kept but NOT added to
    `seen`, so they don't suppress legitimate headings on other pages.
    """
    paragraphs = re.split(r"\n{2,}", body)
    kept, dropped = [], 0

    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        h = para_hash(stripped)
        word_count = len(stripped.split())

        if h in seen:
            dropped += 1
        else:
            kept.append(para)
            if word_count >= min_words:
                seen.add(h)

    return "\n\n".join(kept), len(kept), dropped


def build_section(
    filepath: Path,
    input_dir: Path,
    seen: set[str] | None,
    min_words: int,
) -> tuple[str, int, int]:
    """
    Build a (deduplicated) section for the flattened document.
    Returns (section_text, kept_paragraphs, dropped_paragraphs).
    """
    content = filepath.read_text(encoding="utf-8")
    metadata, body = extract_metadata(content)

    relative = filepath.relative_to(input_dir)
    source_url = metadata.get("source_url", str(relative))

    if seen is not None:
        body, kept, dropped = deduplicate_body(body, seen, min_words)
    else:
        kept = body.count("\n\n") + 1
        dropped = 0

    header = f"## Source: {source_url}\n\n> **File:** `{relative}`\n"
    return header + "\n" + body.strip(), kept, dropped


@click.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--no-dedup", is_flag=True, default=False, help="Disable deduplication")
@click.option(
    "--min-words", default=5, show_default=True,
    help="Min words for a paragraph to enter the seen-set",
)
@click.option("--verbose", "-v", is_flag=True, help="Show per-file dedup stats")
def main(input_dir: Path, output: str | None, no_dedup: bool, min_words: int, verbose: bool):
    """Flatten scraped markdown files in INPUT_DIR into a single RAG document."""

    files = collect_markdown_files(input_dir)
    if not files:
        click.echo(f"❌ No .md files found in {input_dir}")
        sys.exit(1)

    # Determine output path
    if output:
        out_path = Path(output)
    else:
        parts = [p for p in input_dir.parts if p not in (".", "output")]
        slug = "_".join(parts) if parts else input_dir.name
        slug = slug.replace(".", "_")
        out_path = Path(f"{slug}_rag.md")

    dedup_label = "OFF" if no_dedup else f"ON (min-words={min_words})"
    click.echo(f"📂 Input directory: {input_dir}")
    click.echo(f"📄 Found {len(files)} markdown file(s)")
    click.echo(f"🔁 Deduplication:   {dedup_label}")
    click.echo(f"📝 Output file:     {out_path}")
    click.echo("")

    seen: set[str] | None = None if no_dedup else set()
    sections = []
    total_kept = total_dropped = 0

    for i, filepath in enumerate(files, 1):
        try:
            section, kept, dropped = build_section(filepath, input_dir, seen, min_words)
            sections.append(section)
            total_kept += kept
            total_dropped += dropped
            if verbose:
                rel = filepath.relative_to(input_dir)
                click.echo(f"  [{i:>4}/{len(files)}] {rel}  (+{kept} / -{dropped} paragraphs)")
        except Exception as e:
            click.echo(f"  ⚠️  Skipping {filepath}: {e}")

    preamble = (
        f"# Scraped Content from: {input_dir}\n\n"
        f"This document contains {len(sections)} pages scraped from the website.\n"
        f"Each section below corresponds to one page, with its source URL.\n"
    )

    full_doc = preamble + SEPARATOR + SEPARATOR.join(sections)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_doc, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    click.echo(f"\n✨ Done! Wrote {len(sections)} section(s) → {out_path}  ({size_kb:.1f} KB)")
    if not no_dedup:
        click.echo(f"🔁 Dedup: kept {total_kept} paragraphs, dropped {total_dropped} duplicates")
    click.echo("📤 Upload this file to AnythingLLM for RAG ingestion.")


if __name__ == "__main__":
    main()
