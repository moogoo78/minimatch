# Minimatch - Taxonomy Reconciliation

Taxonomy reconciliation against a local minitaxa.db SQLite database or the
Global Names Verifier API.

## Overview

This project contains tools for matching taxonomic names against a local database:

- **minimatch.py** - Local taxonomy reconciliation script
- **reconcile_api.py** - OpenRefine reconciliation API server

## minimatch.py

Reconciles taxonomic names and returns their higher taxa. **The local
minitaxa.db is always matched first; names it cannot resolve fall through to
the fallback backend selected with `--source`.** Each output row's
`according_to` field records which backend actually matched it.

### Matching backends

**Local (always first)** — queries the local minitaxa.db SQLite database:

1. **Higher taxa lookup**: Uses scientific name to query higher taxa from mycobank dataset (dataset_id=1)
   - Returns: `kingdom_name`, `phylum_name`, `class_name`, `order_name`, `family_name`, `genus_name`
2. **Chinese names**: Uses taicol dataset (dataset_id=6) to find Chinese common names
   - Returns: `kingdom_name_zh`, `phylum_name_zh`, `class_name_zh`, `order_name_zh`, `family_name_zh`, `genus_name_zh`

**Fallback — `--source` selects what handles local misses:**

- `local` (default) — no fallback; local matches only.
- `globalnames` — names not found locally are looked up via the
  [Global Names Verifier API](https://verifier.globalnames.org). Returns the
  same `kingdom_name … genus_name` fields, parsed from the best match's
  classification path. **No Chinese names** from this source (the `_zh` columns
  stay empty). `--gn-source` restricts to one or more Global Names *data
  source* ids (e.g. `1`=Catalogue of Life, `11`=GBIF, `12`=EOL); omit it to let
  Global Names pick the best source.

> **Note on id flags:** `--dataset-id` (local minitaxa dataset ids) and
> `--gn-source` (Global Names data source ids) are **separate id spaces**.
> Each applies only to its own backend, so `--dataset-id 1` always means
> mycobank and is never confused with a Global Names source.

### Features

- **Local-first matching**: local SQLite (offline, with Chinese names) is always tried first, with optional Global Names Verifier API fallback for misses
- **Fast**: Direct SQLite queries with closure table for hierarchical data (local backend)
- **Caching**: Species names are cached during processing to avoid redundant queries (one API call per unique name in `globalnames` mode)
- **Handles rank synonyms**: Automatically maps Division ↔ Phylum between datasets
- **Unmatched logging**: Creates a separate CSV file for species that couldn't be matched

### Installation

```bash
# No dependencies needed - uses Python standard library
python3 minimatch.py --help
```

### Usage

#### Basic Usage

```bash
python3 minimatch.py input.csv output.csv
```

#### With Custom Column Names

```bash
python3 minimatch.py input.csv output.csv --species-col "物種學名" --family-col "科名"
```

#### With Custom Database Path

```bash
python3 minimatch.py input.csv output.csv --db /path/to/minitaxa.db
```

#### With Global Names Verifier Fallback

Local DB first; names not found locally fall through to the Global Names
Verifier API.

```bash
# Fall back to GBIF (data source 11) for local misses
python3 minimatch.py input.csv output.csv --source globalnames --gn-source 11

# Fallback across multiple sources, priority order — Catalogue of Life then GBIF
python3 minimatch.py input.csv output.csv --source globalnames --gn-source 1,11

# Fallback to whichever source Global Names judges best
python3 minimatch.py input.csv output.csv --source globalnames
```

#### With Statistics and Verbose Output

```bash
python3 minimatch.py input.csv output.csv --stats -v    # INFO level
python3 minimatch.py input.csv output.csv --stats -vv   # DEBUG level
```

### Command-line Options

```
positional arguments:
  input_csv             Input CSV file
  output_csv            Output CSV file

options:
  --source {local,globalnames}
                        Fallback backend for names not found locally: "local"
                        (no fallback, default) or "globalnames" (Global Names
                        Verifier API). The local DB is always tried first.
  --dataset-id IDS      Comma-separated local minitaxa.db dataset id(s), in
                        priority order; first match wins (default: 1, mycobank)
  --gn-source IDS       [--source globalnames] Comma-separated Global Names data
                        source id(s) for the fallback (e.g. 1=Catalogue of Life,
                        11=GBIF, 12=EOL). Empty (default) lets GN pick the best
  --db DB_PATH          SQLite database path (default: minitaxa.db)
  --species-col NAME    Column name for species scientific name (default: species_name)
  --family-col NAME     Column name for family name (default: family_name)
  --stats, -s           Display reconciliation statistics
  --verbose, -v         Increase verbosity (-v, -vv, -vvv)
```

### Output Fields

The script adds these fields to your output CSV:

**Scientific Names (from mycobank):**
- `kingdom_name`, `phylum_name`, `class_name`, `order_name`, `family_name`, `genus_name`

**Chinese Common Names (from taicol):**
- `kingdom_name_zh`, `phylum_name_zh`, `class_name_zh`, `order_name_zh`, `family_name_zh`, `genus_name_zh`
- Only populated by the `local` backend; empty in `globalnames` mode

**Metadata:**
- `according_to` - Source dataset and version (local), or Global Names data source (globalnames), e.g. `GBIF Backbone Taxonomy (Global Names data source 11)`

### Example

**Input CSV (`fungi-sample.csv`):**
```csv
物種學名,科名
Chlorencoelia torta,Cenangiaceae
Morchella crassipes,Morchellaceae
```

**Command:**
```bash
python3 minimatch.py fungi-sample.csv output.csv --species-col "物種學名" --family-col "科名" --stats
```

**Output CSV:**
```csv
物種學名,科名,kingdom_name,phylum_name,class_name,order_name,family_name,genus_name,kingdom_name_zh,phylum_name_zh,class_name_zh,order_name_zh,family_name_zh,genus_name_zh,according_to
Chlorencoelia torta,Cenangiaceae,Fungi,Ascomycota,Leotiomycetes,Helotiales,Cenangiaceae,Chlorencoelia,真菌界,子囊菌門,錘舌菌綱,柔膜菌目,,,mycobank (version 250113)
Morchella crassipes,Morchellaceae,Fungi,Ascomycota,Pezizomycetes,Pezizales,Morchellaceae,Morchella,真菌界,子囊菌門,盤菌綱,盤菌目,羊肚菌科,羊肚菌屬,mycobank (version 250113)
```

### Database Schema

The script expects the following tables in `minitaxa.db`:

**taxa** - Main taxonomy table
- dataset_id = 1: mycobank (used for hierarchy)
- dataset_id = 6: taicol 260625 (used for Chinese names)
- dataset_id = 3: fishdb
- dataset_id = 4: nmmba
- dataset_id = 2: taicol 251028 (previous version, retained)

**taxa_closure** - Closure table for hierarchical relationships
- Stores ancestor-descendant relationships with depth

**taxa_rank** - Rank names (Kingdom, Phylum, Class, etc.)

**taxa_common_name** - Common names (Chinese)
- lang = 'zh' for Chinese names

**dataset** - Dataset metadata

### Import Scripts

Import taxonomy data into minitaxa.db (import scripts live in `data/loaders/`):

```bash
# Import fish database
python data/loaders/import-fishdb.py data/loaders/checklist-fishdb.csv --dataset-id 3

# Import NMMBA database
python data/loaders/import-nmmba.py data/loaders/checklist-nmmba.csv --dataset-id 4

# Import TaiCOL (uses taicol.ini for config; see data/loaders/import-taicol.py)
python data/loaders/import-taicol.py --config data/loaders/taicol.ini \
    --csv data/loaders/TaiCOL_name_20260625.csv --db minitaxa.db
```

### Limitations

**Local backend:**
1. Only processes species found in mycobank (dataset_id=1) for higher taxa
2. Chinese names only available for taxa in taicol (dataset_id=6)
3. Some higher ranks may not have Chinese common names in the database
4. Requires pre-built closure table for hierarchical queries

**Global Names backend:**
1. No Chinese names (the `_zh` columns stay empty)
2. Requires network access; one API call per unique species name
3. Returned ranks depend on the data source (e.g. GBIF may omit `class` for some taxa)

### Tips

- Use `-v` flag to see which species are being matched
- Use `--stats` to see matching statistics (matched/total percentage)
- Check the `*_unmatched.csv` file for species that couldn't be reconciled
- Ensure your database has both closure table data and common names populated

## reconcile_api.py

OpenRefine reconciliation service for the MiniTaxa database. See [RECONCILE_README.md](RECONCILE_README.md) for full documentation.

### Quick Start

```bash
# Install dependencies
pip install -r requirements-reconcile.txt

# Start the API server
python3 reconcile_api.py

# In OpenRefine: Add Standard Service
# http://localhost:5000/reconcile
```

## Database Status

| Dataset | Records | Description |
|---------|---------|-------------|
| mycobank | 537,737+ | MycoBank fungal taxonomy |
| taicol (260625) | 252,652 | TaiCOL (Taiwan Checklist of Life) — current, dataset_id=6 |
| taicol (251028) | 241,230 | TaiCOL — previous version, dataset_id=2 |
| fishdb | ~10,000+ | Fish database |
| nmmba | ~10,000+ | National Museum of Marine Biology & Aquarium |

## Project Structure

```
minimatch/
├── minimatch.py              # Main reconciliation script (local + Global Names backends)
├── reconcile_api.py          # OpenRefine API server
├── minitaxa.db               # SQLite database (not in git)
├── requirements-reconcile.txt
└── data/
    ├── sql/                  # Schema and seed SQL
    └── loaders/              # Import scripts + source CSVs (not in git)
        ├── import-fishdb.py  # Import script for fish database
        ├── import-nmmba.py   # Import script for NMMBA
        ├── import-taicol.py  # Import script for TaiCOL (+ taicol.ini)
        └── import-mycobank.py # Import script for MycoBank
```

## License

MIT
