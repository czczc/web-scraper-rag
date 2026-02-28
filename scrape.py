#!/usr/bin/env python3
"""
scrape.py — Recursively crawl a website and save each page as markdown.

Usage:
    uv run python scrape.py <URL> [OPTIONS]

Options:
    --output DIR        Output directory (default: ./output)
    --max-pages INT     Maximum number of pages to crawl (default: 100)
    --depth INT         Maximum crawl depth (default: 10)
    --verbose           Enable verbose logging
"""

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urljoin

import click
from tqdm import tqdm

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy


def url_to_filepath(base_url: str, page_url: str, output_dir: Path) -> Path:
    """Convert a URL to a filesystem path under output_dir."""
    parsed = urlparse(page_url)
    # Build path: <output_dir>/<netloc>/<path>.md
    # Strip leading/trailing slashes from path
    url_path = parsed.path.strip("/")
    if not url_path:
        url_path = "index"
    # Remove query string from filename but keep it safe
    if parsed.query:
        safe_query = re.sub(r"[^\w=&-]", "_", parsed.query)[:50]
        url_path = f"{url_path}?{safe_query}"
    # Ensure .md extension
    if not url_path.endswith(".md"):
        url_path = url_path + ".md"
    # Build full path
    filepath = output_dir / parsed.netloc / url_path
    return filepath


def save_markdown(filepath: Path, url: str, markdown: str) -> None:
    """Save markdown content to a file with a metadata header."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    header = f"---\nsource_url: {url}\n---\n\n"
    filepath.write_text(header + markdown, encoding="utf-8")


@click.command()
@click.argument("url")
@click.option("--output", "-o", default="output", help="Output directory", show_default=True)
@click.option("--max-pages", "-n", default=100, help="Max pages to crawl", show_default=True)
@click.option("--depth", "-d", default=10, help="Max crawl depth", show_default=True)
@click.option(
    "--css-selector", "-s", default=None,
    help=(
        "CSS selector to restrict content extraction to (e.g. '#mw-content-text' for MediaWiki, "
        "'article' or 'main' for most modern sites). "
        "Strips nav/sidebar/footer from the output entirely."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def main(url: str, output: str, max_pages: int, depth: int, css_selector: str | None, verbose: bool):
    """Crawl URL recursively and save each page as a markdown file."""
    asyncio.run(_crawl(url, output, max_pages, depth, css_selector, verbose))


async def _crawl(url: str, output: str, max_pages: int, depth: int, css_selector: str | None, verbose: bool):
    output_dir = Path(output)
    parsed = urlparse(url)
    base_domain = parsed.netloc
    base_path = parsed.path.rstrip("/")

    click.echo(f"🌐 Starting crawl of: {url}")
    click.echo(f"📂 Output directory:  {output_dir / base_domain}")
    click.echo(f"📄 Max pages: {max_pages}  |  Max depth: {depth}")
    if css_selector:
        click.echo(f"🎯 CSS selector:      {css_selector}")
    else:
        click.echo("🎯 CSS selector:      (none — full page)")
    click.echo("")

    browser_config = BrowserConfig(
        headless=True,
        verbose=verbose,
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # Use DefaultMarkdownGenerator without content filtering so all links
        # (including external references) are preserved in the output.
        markdown_generator=DefaultMarkdownGenerator(),
        # If a CSS selector is given, Crawl4AI only converts that DOM subtree
        # to markdown — sidebar/nav/footer HTML never enters the output.
        css_selector=css_selector,
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=depth,
            max_pages=max_pages,
        ),
        verbose=verbose,
        stream=True,
    )

    saved = 0
    skipped = 0

    async with AsyncWebCrawler(config=browser_config) as crawler:
        click.echo("🔍 Crawling... (this may take a while)\n")
        
        async for result in await crawler.arun(url=url, config=run_config):
            page_url = result.url

            # Only keep pages within the same domain and base path
            parsed_page = urlparse(page_url)
            if parsed_page.netloc != base_domain:
                skipped += 1
                continue
            if base_path and not parsed_page.path.startswith(base_path):
                skipped += 1
                continue

            if not result.success:
                if verbose:
                    click.echo(f"  ⚠️  Failed: {page_url} — {result.error_message}")
                skipped += 1
                continue

            # Use raw_markdown to preserve all hyperlinks (including external URLs).
            # fit_markdown runs PruningContentFilter which can drop link-heavy sections.
            md = result.markdown
            if hasattr(md, "raw_markdown") and md.raw_markdown:
                content = md.raw_markdown
            elif isinstance(md, str):
                content = md
            else:
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
        sys.exit(1)


if __name__ == "__main__":
    main()
