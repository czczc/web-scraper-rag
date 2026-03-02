# web-scraper

A `uv`-managed Python tool to scrape websites into clean markdown and flatten them into a single document for [AnythingLLM](https://anythingllm.com/) RAG ingestion.

## Setup

```bash
# Install dependencies
uv sync

# Install Playwright browser (one-time)
uv run crawl4ai-setup
```

## Usage

### 1. Scrape — `scrape.py`

Recursively crawls a site (BFS) and saves each page as a markdown file under `output/<domain>/`.

```
uv run python scrape.py <URL> [OPTIONS]

Options:
  -o, --output DIR              Output directory  [default: output]
  -n, --max-pages INT           Max pages to crawl  [default: 100]
  -d, --depth INT               Max crawl depth  [default: 10]
  -s, --css-selector TEXT       Restrict extraction AND BFS link discovery to a
                                CSS element. Use when internal nav is INSIDE the
                                selected element (e.g. MediaWiki).
  -e, --excluded-selector TEXT  Remove these elements from extracted content while
                                still discovering links through them. Use when
                                internal nav is OUTSIDE the content area
                                (e.g. Jekyll sites with links in <header>).
  -v, --verbose                 Enable verbose output
```

**Example:**

```bash
# MediaWiki — nav is inside #mw-content-text, use --css-selector
uv run python scrape.py https://www.phy.bnl.gov/computing \
    --max-pages 50 \
    --css-selector "#mw-content-text"

# Jekyll static site — nav links are in <header>, use --excluded-selector
# (two-phase: BFS discovers all pages first, then re-fetches with header stripped)
uv run python scrape.py https://www.phy.bnl.gov/edg/ \
    --max-pages 50 \
    --excluded-selector "header, footer"

# No selector — full page content (useful for auditing first)
uv run python scrape.py https://docs.example.com --max-pages 20
```

#### Which option to use?

| Scenario | Option | Example |
|---|---|---|
| Nav **inside** content area | `--css-selector` | MediaWiki `#mw-content-text` |
| Nav **outside** content (header/sidebar) | `--excluded-selector` | Jekyll `header, footer, nav` |
| WordPress / Docs sites | `--css-selector` | `article`, `main`, `.entry-content` |
| Docusaurus / ReadTheDocs | `--css-selector` | `article`, `.markdown` |
| No selector | *(none)* | Full page including nav |

---

### 2. Flatten — `flatten.py`

Walks the `output/` directory and concatenates all `.md` files into a single RAG document with source URL headers. Removes duplicate paragraphs (nav boilerplate that survives across pages) by default.

```
uv run python flatten.py <INPUT_DIR> [OPTIONS]

Options:
  -o, --output FILE     Output file  [default: <slug>_rag.md]
  --no-dedup            Disable paragraph-level deduplication
  --min-words INT       Min words for a paragraph to enter the seen-set  [default: 5]
  -v, --verbose         Show per-file dedup stats
```

**Example:**

```bash
uv run python flatten.py output/www.phy.bnl.gov --verbose
# → www_phy_bnl_gov_rag.md
```

---

### 3. Upload to AnythingLLM

Upload the generated `*_rag.md` file via the AnythingLLM document manager. Each section includes a `source_url` header so the LLM can cite the original page.

---

## Output layout

```
output/
└── www.phy.bnl.gov/
    └── computing/
        ├── index.php?title=Computer_Security.md
        ├── index.php?title=BNL_Remote_Access.md
        └── ...

www_phy_bnl_gov_rag.md        ← upload this to AnythingLLM
```

## How it works

```
scrape.py                              flatten.py
──────────────────────────────         ──────────────────────────────
URL → BFS deep-crawl (Crawl4AI)        output/ directory
    → CSS selector → article DOM           → walk all .md files
    → markdown (links preserved)            → deduplicate paragraphs
    → save output/<domain>/path.md          → concat with source headers
                                            → single *_rag.md file
```
