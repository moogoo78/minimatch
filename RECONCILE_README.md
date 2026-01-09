# MiniTaxa Reconciliation API

OpenRefine reconciliation service for the MiniTaxa taxonomy database.

## Features

- **Full reconciliation support**: Match taxonomic names against your database
- **Fuzzy matching**: Find similar names even with typos
- **Type filtering**: Filter by taxonomic rank (species, genus, family, etc.)
- **Dataset filtering**: Search within specific datasets (mycobank, taicol, fishdb, nmmba)
- **Multi-language**: Supports matching by scientific names and Chinese common names
- **Preview**: Visual preview of taxa with full lineage
- **Autocomplete**: Suggest entities and types as you type

## Installation

1. Install dependencies:
```bash
pip install -r requirements-reconcile.txt
```

2. Make sure `minitaxa.db` is in the same directory

## Running the API

Start the server:
```bash
python reconcile_api.py
```

The API will be available at `http://localhost:5000/reconcile`

## Testing

Run the test suite:
```bash
# In another terminal (while API is running)
python test_reconcile.py
```

## Using with OpenRefine

### 1. Add the reconciliation service

In OpenRefine:
1. Select a column with taxonomic names
2. Click **Reconcile** → **Start reconciling...**
3. Click **Add Standard Service...**
4. Enter: `http://localhost:5000/reconcile`
5. Click **Add Service**

### 2. Configure reconciliation

- **Reconcile each cell to an entity of one of these types**: Select rank (Species, Genus, etc.)
- Adjust **Auto-match candidates with high confidence** threshold as needed

### 3. Review matches

- Green cells: Automatic matches (high confidence)
- Yellow cells: Multiple candidates (click to choose)
- Use facets to filter by match status

## API Endpoints

### Service Metadata
```bash
GET /reconcile
```

Returns service information and capabilities.

### Reconcile
```bash
POST /reconcile
Content-Type: application/x-www-form-urlencoded

queries={"q0": {"query": "Agaricus aureus", "type": "/taxa/species", "limit": 5}}
```

Returns matching candidates with scores.

### Suggest Entity
```bash
GET /suggest/entity?prefix=Agar
```

Returns autocomplete suggestions for taxa names.

### Suggest Type
```bash
GET /suggest/type?prefix=spec
```

Returns autocomplete suggestions for taxonomic ranks.

### Preview
```bash
GET /preview/{taxa_id}
```

Returns HTML preview of a taxon with full details and lineage.

### Health Check
```bash
GET /health
```

Returns service health and database statistics.

## Query Parameters

### Type Filtering

Filter by taxonomic rank:
```json
{
  "query": "Agaricus",
  "type": "/taxa/genus"
}
```

Available types: species, genus, family, order, class, phylum, kingdom, etc.

### Dataset Filtering

Filter by source dataset using properties:
```json
{
  "query": "Agaricus aureus",
  "properties": [
    {
      "pid": "dataset",
      "v": "mycobank"
    }
  ]
}
```

Available datasets:
- `mycobank` - MycoBank fungal taxonomy
- `taicol` - TaiCOL (Taiwan Checklist of Life)
- `fishdb` - Fish database
- `nmmba` - National Museum of Marine Biology & Aquarium

## Scoring Algorithm

The API uses a multi-factor scoring system:

1. **String similarity**: SequenceMatcher ratio (0-100)
2. **Exact match bonus**: 100 for exact name matches
3. **Common name matching**: Also checks Chinese common names
4. **Match threshold**: 95+ score considered definite match

## Examples

### Example 1: Simple reconciliation
```bash
curl -X POST http://localhost:5000/reconcile \
  -d 'queries={"q0":{"query":"Acanthurus japonicus"}}'
```

### Example 2: With type filter
```bash
curl -X POST http://localhost:5000/reconcile \
  -d 'queries={"q0":{"query":"Acanthurus","type":"/taxa/genus"}}'
```

### Example 3: Chinese common name
```bash
curl -X POST http://localhost:5000/reconcile \
  -d 'queries={"q0":{"query":"日本糯鰻屬"}}'
```

### Example 4: Autocomplete
```bash
curl "http://localhost:5000/suggest/entity?prefix=Acanth"
```

## Response Format

### Reconciliation Response
```json
{
  "q0": {
    "result": [
      {
        "id": "123456",
        "name": "Acanthurus japonicus (Schmidt, 1931)",
        "type": [
          {
            "id": "/taxa/species",
            "name": "Species"
          }
        ],
        "score": 100,
        "match": true,
        "description": "日本刺尾鯛 | valid | [fishdb]"
      }
    ]
  }
}
```

## Troubleshooting

### Port already in use
Change the port in `reconcile_api.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5001)  # Use different port
```

### Database not found
Ensure `minitaxa.db` is in the same directory or update `DB_PATH`:
```python
DB_PATH = '/path/to/minitaxa.db'
```

### CORS issues
CORS is enabled by default. If you still have issues, check your OpenRefine settings.

### Slow queries
For large datasets, consider:
- Adding indexes: `CREATE INDEX idx_taxa_name_lower ON taxa(LOWER(name))`
- Limiting result count
- Filtering by dataset

## Advanced Usage

### Custom similarity algorithm

Edit the `similarity_score()` function to use different algorithms:
- Levenshtein distance
- Jaro-Winkler
- Soundex for phonetic matching

### Adding metadata

Extend the `format_result()` function to include additional fields:
- Authors and year
- Vernacular names
- Geographic distribution
- External links

## License

This reconciliation API is provided as-is for use with your MiniTaxa database.
