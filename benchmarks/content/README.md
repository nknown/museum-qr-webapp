# Controlled presentation population

`POPULATE_PRESENTATIONS.py` reproduces the authored content used for the final
populated-content performance campaign. It drives the Wagtail CMS through
Playwright, using the same administration interface available to a curator.

For each of the original 28 piece presentations, it publishes six authored
slides in addition to the automatic details slide. The authored pattern is:

1. image and object overview;
2. text-only function and use;
3. image and materials description;
4. piece-specific two-page PDF;
5. image and historical context;
6. image and interactive comparison question.

Each presentation receives four distinct image URLs and one distinct PDF.
Images are not reused across presentations. The generated colours, layouts,
text identifiers, and filenames are derived from catalogue content and hashes,
so the dataset is deterministic and reproducible rather than randomly changing
between runs. This prevents an unrealistically cache-friendly dataset while
keeping repeated experiments comparable.

## Snapshot dependency

This is the script used for the controlled thesis snapshot, not a general CMS
fixture command. It contains the 28 Wagtail User Device parent page IDs and the
14 existing collection-image IDs from that database snapshot. It also expects
exactly 28 public presentation paths in the same order.

Do not run it against another database without reviewing
`USER_DEVICE_PAGE_IDS`, `ANCIENT_IMAGE_IDS`, and the path order. Incorrect IDs
could publish content under unrelated pages. Back up both the database and
uploaded media before running it.

## Requirements

- A running MIYP deployment with the controlled content snapshot.
- A CMS account allowed to add images, documents, pages, and publish pages.
- Python 3, Google Chrome at `/usr/bin/google-chrome`, and the packages below.

Install the authoring dependencies in an isolated environment:

```bash
python -m pip install -r benchmarks/content/requirements.txt
```

Create `benchmarks/content/presentations.txt` with one published User Device
presentation path per line. It must contain exactly 28 paths corresponding to
the hardcoded parent-page order. Real paths are deliberately excluded from Git.

## Populate

Set credentials in the process environment rather than writing them to a file:

```bash
export MIYP_CMS_BASE_URL=https://127.0.0.1:8000
export MIYP_CMS_USER=your-cms-username
export MIYP_CMS_PASSWORD='your-cms-password'
python benchmarks/content/POPULATE_PRESENTATIONS.py
```

The script is idempotent for its expected slide titles: it updates matching
slides and creates missing ones. It creates generated input assets under
`generated_benchmark_media/`, uploads them through the CMS, publishes the
slides, and finally checks the anonymous public presentation representation.

To validate an already populated snapshot without modifying it:

```bash
MIYP_VERIFY_ONLY=1 python benchmarks/content/POPULATE_PRESENTATIONS.py
```

## Verification output

Successful verification requires every piece presentation to expose seven
slides, six authored headings, four distinct images, one PDF, and one
interactive question. The script also rejects image reuse between pieces.

It writes `PRESENTATION_CONTENT_MANIFEST.json`, which records the content
pattern and per-presentation checks. Generated media, the manifest, the private
path list, and credentials are local experimental artifacts and are not
committed to this repository.
