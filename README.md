# Minimatch - Local Taxonomy Reconciliation

Local taxonomy reconciliation using minitaxa.db SQLite database.

## Overview

This project contains tools for matching taxonomic names against a local database:

- **minimatch.py** - Local taxonomy reconciliation script
- **reconcile_api.py** - OpenRefine reconciliation API server

## minimatch.py

Queries a local SQLite database for taxonomy reconciliation. It performs two main steps:

1. **Higher taxa lookup**: Uses scientific name to query higher taxa from mycobank dataset (dataset_id=1)
   - Returns: `kingdom_name`, `phylum_name`, `class_name`, `order_name`, `family_name`, `genus_name`

2. **Chinese names**: Uses taicol dataset (dataset_id=2) to find Chinese common names
   - Returns: `kingdom_name_zh`, `phylum_name_zh`, `class_name_zh`, `order_name_zh`, `family_name_zh`, `genus_name_zh`

### Features

- **No API calls**: All data queried from local minitaxa.db
- **Fast**: Direct SQLite queries with closure table for hierarchical data
- **Caching**: Species names are cached during processing to avoid redundant queries
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

**Metadata:**
- `according_to` - Source dataset and version

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
- dataset_id = 2: taicol (used for Chinese names)
- dataset_id = 3: fishdb
- dataset_id = 4: nmmba

**taxa_closure** - Closure table for hierarchical relationships
- Stores ancestor-descendant relationships with depth

**taxa_rank** - Rank names (Kingdom, Phylum, Class, etc.)

**taxa_common_name** - Common names (Chinese)
- lang = 'zh' for Chinese names

**dataset** - Dataset metadata

### Import Scripts

Import taxonomy data into minitaxa.db:

```bash
# Import fish database
python tmp/import-fishdb.py data/loaders/checklist-fishdb.csv --dataset-id 3

# Import NMMBA database
python tmp/import-nmmba.py data/loaders/checklist-nmmba.csv --dataset-id 4
```

### Limitations

1. Only processes species found in mycobank (dataset_id=1) for higher taxa
2. Chinese names only available for taxa in taicol (dataset_id=2)
3. Some higher ranks may not have Chinese common names in the database
4. Requires pre-built closure table for hierarchical queries

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
| taicol | 241,230+ | TaiCOL (Taiwan Checklist of Life) |
| fishdb | ~10,000+ | Fish database |
| nmmba | ~10,000+ | National Museum of Marine Biology & Aquarium |

## Project Structure

```
minimatch/
├── minimatch.py              # Main reconciliation script
├── reconcile_api.py          # OpenRefine API server
├── minitaxa.db              # SQLite database (not in git)
├── requirements-reconcile.txt
├── tmp/
│   ├── import-fishdb.py     # Import script for fish database
│   ├── import-nmmba.py      # Import script for NMMBA
│   └── test_reconcile.py    # API test suite
└── data/
    └── loaders/             # Source CSV files (not in git)

## License

MIT
