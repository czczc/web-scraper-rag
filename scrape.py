#!/usr/bin/env python3
"""
scrape.py — Recursively crawl a website and save each page as markdown.

Usage:
    uv run python scrape.py <URL> [OPTIONS]

Options:
    --output DIR                Output directory (default: ./output)
    --max-pages INT             Maximum number of pages to crawl (default: 100)
    --depth INT                 Maximum crawl depth (default: 10)
    --css-selector TEXT         Restrict extraction to a CSS element (also blocks BFS
                                from following links outside that element — only use
                                when internal nav is INSIDE the selected element, e.g.
                                '#mw-content-text' for MediaWiki)
    --excluded-selector TEXT    Remove these elements from extracted content, but still
                                use the full page for BFS link discovery (e.g.
                                'header, footer, nav' for Jekyll/static sites where
                                internal links live in a <header> that you want stripped)
    --verbose                   Enable verbose logging
"""

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import click

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy


def url_to_filepath(base_url: str, page_url: str, output_dir: Path) -> Path:
    """Convert a URL to a filesystem path under output_dir."""
    parsed = urlparse(page_url)
    url_path = parsed.path.strip("/")
    if not url_path:
        url_path = "index"
    if parsed.query:
        safe_query = re.sub(r"[^\w=&-]", "_", parsed.query)[:50]
        url_path = f"{url_path}?{safe_query}"
    if not url_path.endswith(".md"):
        url_path = url_path + ".md"
    return output_dir / parsed.netloc / url_path


def save_markdown(filepath: Path, url: str, markdown: str) -> None:
    """Save markdown content to a file with a metadata header."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    header = f"---\nsource_url: {url}\n---\n\n"
    filepath.write_text(header + markdown, encoding="utf-8")


def in_scope(page_url: str, base_domain: str, base_path: str) -> bool:
    """Return True if page_url is within the target domain and path prefix."""
    p = urlparse(page_url)
    if p.netloc != base_domain:
        return False
    if base_path and not p.path.startswith(base_path):
        return False
    return True


def extract_content(result) -> str | None:
    """Pull raw_markdown from a Crawl4AI result, or None if empty."""
    md = result.markdown
    if hasattr(md, "raw_markdown") and md.raw_markdown:
        return md.raw_markdown
    if isinstance(md, str) and md:
        return md
    return None


@click.command()
@click.argument("url")
@click.option("--output", "-o", default="output", help="Output directory", show_default=True)
@click.option("--max-pages", "-n", default=100, help="Max pages to crawl", show_default=True)
@click.option("--depth", "-d", default=10, help="Max crawl depth", show_default=True)
@click.option(
    "--css-selector", "-s", default=None,
    help=(
        "CSS selector to restrict extraction to (e.g. '#mw-content-text' for MediaWiki). "
        "⚠ Also restricts BFS link discovery — use --excluded-selector instead when nav "
        "links are outside the selected element."
    ),
)
@click.option(
    "--excluded-selector", "-e", default=None,
    help=(
        "CSS selector for elements to REMOVE from extracted content. "
        "Unlike --css-selector, the full page DOM is still used for BFS link discovery. "
        "Use this for sites where internal links live in nav/header "
        "(e.g. 'header, footer, nav' for Jekyll sites)."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def main(
    url: str, output: str, max_pages: int, depth: int,
    css_selector: str | None, excluded_selector: str | None, verbose: bool,
):
    """Crawl URL recursively and save each page as a markdown file."""
    asyncio.run(_crawl(url, output, max_pages, depth, css_selector, excluded_selector, verbose))


async def _crawl(
    url: str, output: str, max_pages: int, depth: int,
    css_selector: str | None, excluded_selector: str | None, verbose: bool,
):
    output_dir = Path(output)
    parsed = urlparse(url)
    base_domain = parsed.netloc
    base_path = parsed.path.rstrip("/")

    click.echo(f"🌐 Starting crawl of: {url}")
    click.echo(f"📂 Output directory:  {output_dir / base_domain}")
    click.echo(f"📄 Max pages: {max_pages}  |  Max depth: {depth}")
    if css_selector:
        click.echo(f"🎯 CSS selector:      {css_selector}  (restricts link discovery too)")
    if excluded_selector:
        click.echo(f"🚫 Excluded selector: {excluded_selector}  (links still discovered)")
    if not css_selector and not excluded_selector:
        click.echo("🎯 Content filter:    (none — full page)")
    click.echo("")

    browser_config = BrowserConfig(headless=True, verbose=verbose)

    # ── Phase 1: BFS discovery ────────────────────────────────────────────
    # Run WITHOUT any content selectors so the crawler can follow ALL links
    # on each page (including those inside nav/header/footer).  We collect
    # every in-scope URL that the BFS visits.
    #
    # When --css-selector is set we trust the user knows the nav is inside
    # the selected element, so we skip Phase 1 and do everything in Phase 2.
    needs_two_phase = bool(excluded_selector) and not css_selector

    discovered_urls: list[str] = []

    if needs_two_phase:
        click.echo("🔍 Phase 1: discovering all pages (full-page BFS)…\n")
        discovery_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            markdown_generator=DefaultMarkdownGenerator(),
            deep_crawl_strategy=BFSDeepCrawlStrategy(
                max_depth=depth,
                max_pages=max_pages,
            ),
            verbose=verbose,
            stream=True,
        )
        async with AsyncWebCrawler(config=browser_config) as crawler:
            async for result in await crawler.arun(url=url, config=discovery_config):
                page_url = result.url
                if in_scope(page_url, base_domain, base_path):
                    discovered_urls.append(page_url)
                    if verbose:
                        click.echo(f"  🔗 Discovered: {page_url}")

        click.echo(f"\n  Found {len(discovered_urls)} in-scope page(s).\n")

        # ── Phase 2: re-fetch with content filtering ──────────────────────
        click.echo("🖊  Phase 2: extracting clean content…\n")
        extract_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            markdown_generator=DefaultMarkdownGenerator(),
            excluded_selector=excluded_selector,
            verbose=verbose,
        )

        saved = skipped = 0
        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun_many(
                urls=discovered_urls,
                config=extract_config,
            )
            for result in results:
                page_url = result.url
                if not result.success:
                    if verbose:
                        click.echo(f"  ⚠️  Failed: {page_url} — {result.error_message}")
                    skipped += 1
                    continue
                content = extract_content(result)
                if not content:
                    if verbose:
                        click.echo(f"  ⚠️  No markdown for: {page_url}")
                    skipped += 1
                    continue
                filepath = url_to_filepath(url, page_url, output_dir)
                save_markdown(filepath, page_url, content)
                saved += 1
                click.echo(f"  ✅ [{saved:>4}] {page_url}")
                click.echo(f"         → {filepath}")

    else:
        # ── Single-phase: BFS with optional css_selector ──────────────────
        click.echo("🔍 Crawling… (this may take a while)\n")
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            markdown_generator=DefaultMarkdownGenerator(),
            css_selector=css_selector,
            deep_crawl_strategy=BFSDeepCrawlStrategy(
                max_depth=depth,
                max_pages=max_pages,
            ),
            verbose=verbose,
            stream=True,
        )

        saved = skipped = 0
        async with AsyncWebCrawler(config=browser_config) as crawler:
            async for result in await crawler.arun(url=url, config=run_config):
                page_url = result.url
                if not in_scope(page_url, base_domain, base_path):
                    skipped += 1
                    continue
                if not result.success:
                    if verbose:
                        click.echo(f"  ⚠️  Failed: {page_url} — {result.error_message}")
                    skipped += 1
                    continue
                content = extract_content(result)
                if not content:
                    if verbose:
                        click.echo(f"  ⚠️  No markdown for: {page_url}")
                    skipped += 1
                    continue
                filepath = url_to_filepath(url, page_url, output_dir)
                save_markdown(filepath, page_url, content)
                saved += 1
                click.echo(f"  ✅ [{saved:>4}] {page_url}")
                click.echo(f"         → {filepath}")

    click.echo(f"\n✨ Done! Saved {saved} page(s), skipped {skipped}.")
    click.echo(f"📁 Output: {output_dir / base_domain}/")

    if saved == 0:
        click.echo("\n⚠️  No pages were saved. Tips:")
        click.echo("   - Make sure the URL is accessible")
        click.echo("   - Try increasing --max-pages or --depth")
        click.echo("   - Inspect the site structure and adjust --css-selector or --excluded-selector")
        sys.exit(1)


if __name__ == "__main__":
    main()
