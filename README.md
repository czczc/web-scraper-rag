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
  -o, --output DIR          Output directory  [default: output]
  -n, --max-pages INT       Max pages to crawl  [default: 100]
  -d, --depth INT           Max crawl depth  [default: 10]
  -s, --css-selector TEXT   CSS selector to restrict extraction to main content,
                            stripping nav/sidebar/footer entirely.
  -v, --verbose             Enable verbose output
```

**Example:**

```bash
# Scrape a MediaWiki site — use #mw-content-text to skip nav/sidebar
uv run python scrape.py https://www.phy.bnl.gov/computing \
    --max-pages 50 \
    --css-selector "#mw-content-text"

# Scrape a modern site with a <main> content element
uv run python scrape.py https://docs.example.com \
    --css-selector "main"
```

#### CSS selector by site type

| Site type | Recommended selector |
|---|---|
| MediaWiki | `#mw-content-text` |
| WordPress | `article`, `.entry-content` |
| Docusaurus / ReadTheDocs | `article`, `.markdown` |
| Most modern sites | `main`, `article` |
| *(none)* | Full page including nav |

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
