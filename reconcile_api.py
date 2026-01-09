#!/usr/bin/env python3
"""
OpenRefine Reconciliation API for MiniTaxa Database

Usage:
    python reconcile_api.py

Then in OpenRefine:
    Add reconciliation service: http://localhost:5000/reconcile
"""

import json
import sqlite3
from difflib import SequenceMatcher
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for OpenRefine

# Configuration
DB_PATH = 'minitaxa.db'
SERVICE_NAME = 'MiniTaxa Reconciliation Service'
IDENTIFIER_SPACE = 'http://minitaxa.local/taxa'
SCHEMA_SPACE = 'http://minitaxa.local/schema'


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def similarity_score(a, b):
    """Calculate similarity score between two strings (0-100)."""
    if not a or not b:
        return 0
    return int(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)


def search_taxa(query, type_filter=None, limit=5, dataset_filter=None):
    """
    Search for taxa matching the query.

    Args:
        query: Search string
        type_filter: Rank type filter (e.g., "/taxa/species")
        limit: Maximum number of results
        dataset_filter: Dataset name to filter by

    Returns:
        List of matching taxa with scores
    """
    conn = get_db()
    cur = conn.cursor()

    # Build SQL query
    sql = '''
        SELECT
            t.id,
            t.name,
            t.authors,
            t.year,
            tr.name as rank,
            ts.name as status,
            d.name as dataset,
            tc.name as common_name
        FROM taxa t
        LEFT JOIN taxa_rank tr ON t.rank_id = tr.id
        LEFT JOIN taxa_status ts ON t.status_id = ts.id
        LEFT JOIN dataset d ON t.dataset_id = d.id
        LEFT JOIN taxa_common_name tc ON t.id = tc.taxa_id AND tc.lang = 'zh' AND tc.sort = 1
        WHERE 1=1
    '''
    params = []

    # Apply rank filter
    if type_filter:
        rank_name = type_filter.replace('/taxa/', '')
        sql += ' AND LOWER(tr.name) = LOWER(?)'
        params.append(rank_name)

    # Apply dataset filter
    if dataset_filter:
        sql += ' AND LOWER(d.name) = LOWER(?)'
        params.append(dataset_filter)

    # Search by name (exact or fuzzy)
    sql += ' AND (LOWER(t.name) LIKE LOWER(?) OR LOWER(tc.name) LIKE LOWER(?))'
    search_pattern = f'%{query}%'
    params.extend([search_pattern, search_pattern])

    sql += ' ORDER BY t.name LIMIT ?'
    params.append(limit * 3)  # Get more for scoring

    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()

    # Score results
    scored_results = []
    for row in results:
        # Calculate base score from name similarity
        name_score = similarity_score(query, row['name'])

        # Also check common name
        common_score = 0
        if row['common_name']:
            common_score = similarity_score(query, row['common_name'])

        # Use the better score
        score = max(name_score, common_score)

        # Boost score for exact matches
        if query.lower() == row['name'].lower():
            score = 100
        elif row['common_name'] and query.lower() == row['common_name'].lower():
            score = 100

        # Create full name with author and year
        full_name = row['name']
        if row['authors']:
            full_name += f" {row['authors']}"
            if row['year']:
                full_name += f", {row['year']}"

        scored_results.append({
            'id': str(row['id']),
            'name': row['name'],
            'full_name': full_name,
            'common_name': row['common_name'],
            'rank': row['rank'],
            'status': row['status'],
            'dataset': row['dataset'],
            'score': score,
            'match': score >= 95  # Consider 95+ as definite match
        })

    # Sort by score and limit
    scored_results.sort(key=lambda x: x['score'], reverse=True)
    return scored_results[:limit]


def format_result(result):
    """Format a search result for OpenRefine."""
    type_list = []
    if result['rank']:
        type_list.append({
            'id': f"/taxa/{result['rank'].lower()}",
            'name': result['rank']
        })

    # Build description
    description_parts = []
    if result['common_name']:
        description_parts.append(result['common_name'])
    if result['status']:
        description_parts.append(result['status'])
    if result['dataset']:
        description_parts.append(f"[{result['dataset']}]")

    formatted = {
        'id': result['id'],
        'name': result['full_name'],
        'type': type_list,
        'score': result['score'],
        'match': result['match']
    }

    if description_parts:
        formatted['description'] = ' | '.join(description_parts)

    return formatted


@app.route('/reconcile', methods=['GET', 'POST'])
def reconcile():
    """Main reconciliation endpoint."""

    # GET request: return service metadata
    if request.method == 'GET':
        # Get available ranks for defaultTypes
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT DISTINCT tr.name, COUNT(*) as count
            FROM taxa t
            JOIN taxa_rank tr ON t.rank_id = tr.id
            GROUP BY tr.name
            ORDER BY count DESC
            LIMIT 10
        ''')
        ranks = cur.fetchall()
        conn.close()

        default_types = [
            {
                'id': f"/taxa/{row['name'].lower()}",
                'name': row['name']
            }
            for row in ranks
        ]

        metadata = {
            'versions': ['0.2'],
            'name': SERVICE_NAME,
            'identifierSpace': IDENTIFIER_SPACE,
            'schemaSpace': SCHEMA_SPACE,
            'defaultTypes': default_types,
            'view': {
                'url': f'{IDENTIFIER_SPACE}/{{{{id}}}}'
            },
            'preview': {
                'url': request.url_root + 'preview/{{id}}',
                'width': 400,
                'height': 300
            },
            'suggest': {
                'entity': {
                    'service_url': request.url_root + 'reconcile',
                    'service_path': '/suggest/entity'
                },
                'type': {
                    'service_url': request.url_root + 'reconcile',
                    'service_path': '/suggest/type'
                }
            }
        }

        # Handle JSONP callback
        callback = request.args.get('callback')
        if callback:
            return f"{callback}({json.dumps(metadata)})", 200, {'Content-Type': 'application/javascript'}
        return jsonify(metadata)

    # POST request: process reconciliation queries
    queries = request.form.get('queries')
    if not queries:
        return jsonify({'error': 'No queries provided'}), 400

    queries = json.loads(queries)
    results = {}

    for query_id, query_data in queries.items():
        query_string = query_data.get('query', '')
        type_filter = query_data.get('type')
        limit = query_data.get('limit', 5)

        # Extract dataset from properties if provided
        dataset_filter = None
        if 'properties' in query_data:
            for prop in query_data['properties']:
                if prop.get('pid') == 'dataset':
                    dataset_filter = prop.get('v')
                    break

        # Search for matches
        matches = search_taxa(query_string, type_filter, limit, dataset_filter)

        # Format results
        results[query_id] = {
            'result': [format_result(match) for match in matches]
        }

    return jsonify(results)


@app.route('/suggest/entity', methods=['GET'])
def suggest_entity():
    """Entity suggestion endpoint for autocomplete."""
    prefix = request.args.get('prefix', '')
    cursor = request.args.get('cursor', 0)
    limit = 10

    if not prefix:
        return jsonify({'result': []})

    matches = search_taxa(prefix, limit=limit)

    suggestions = [{
        'id': match['id'],
        'name': match['full_name'],
        'description': match.get('common_name', '')
    } for match in matches]

    return jsonify({
        'result': suggestions
    })


@app.route('/suggest/type', methods=['GET'])
def suggest_type():
    """Type (rank) suggestion endpoint."""
    prefix = request.args.get('prefix', '')

    conn = get_db()
    cur = conn.cursor()

    if prefix:
        cur.execute('''
            SELECT DISTINCT tr.name
            FROM taxa_rank tr
            WHERE LOWER(tr.name) LIKE LOWER(?)
            ORDER BY tr.name
            LIMIT 10
        ''', (f'%{prefix}%',))
    else:
        cur.execute('''
            SELECT DISTINCT tr.name
            FROM taxa_rank tr
            ORDER BY tr.name
            LIMIT 10
        ''')

    ranks = cur.fetchall()
    conn.close()

    suggestions = [{
        'id': f"/taxa/{row['name'].lower()}",
        'name': row['name']
    } for row in ranks]

    return jsonify({
        'result': suggestions
    })


@app.route('/preview/<taxa_id>')
def preview(taxa_id):
    """Preview endpoint showing taxa details."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        SELECT
            t.id,
            t.name,
            t.authors,
            t.year,
            tr.name as rank,
            ts.name as status,
            d.name as dataset,
            t.source_id,
            GROUP_CONCAT(tc.name, ', ') as common_names
        FROM taxa t
        LEFT JOIN taxa_rank tr ON t.rank_id = tr.id
        LEFT JOIN taxa_status ts ON t.status_id = ts.id
        LEFT JOIN dataset d ON t.dataset_id = d.id
        LEFT JOIN taxa_common_name tc ON t.id = tc.taxa_id
        WHERE t.id = ?
        GROUP BY t.id
    ''', (taxa_id,))

    row = cur.fetchone()

    if not row:
        conn.close()
        return '<html><body>Taxa not found</body></html>', 404

    # Get parent taxa
    cur.execute('''
        SELECT
            t.id,
            t.name,
            tr.name as rank,
            tc.depth
        FROM taxa_closure tc
        JOIN taxa t ON tc.ancestor_id = t.id
        LEFT JOIN taxa_rank tr ON t.rank_id = tr.id
        WHERE tc.descendant_id = ? AND tc.depth > 0
        ORDER BY tc.depth DESC
    ''', (taxa_id,))

    parents = cur.fetchall()

    # Get children count
    cur.execute('''
        SELECT COUNT(*) as count
        FROM taxa_closure
        WHERE ancestor_id = ? AND depth = 1
    ''', (taxa_id,))

    children_count = cur.fetchone()['count']
    conn.close()

    # Build HTML preview
    html = f'''
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 15px; }}
            h1 {{ font-size: 18px; margin: 0 0 10px 0; }}
            .scientific {{ font-style: italic; }}
            .info {{ margin: 5px 0; color: #666; }}
            .lineage {{ margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 4px; }}
            .lineage-item {{ margin: 2px 0; }}
            .label {{ font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1><span class="scientific">{row['name']}</span></h1>
    '''

    if row['authors']:
        html += f'<div class="info">Author: {row["authors"]}'
        if row['year']:
            html += f', {row["year"]}'
        html += '</div>'

    if row['common_names']:
        html += f'<div class="info">Common name: {row["common_names"]}</div>'

    if row['rank']:
        html += f'<div class="info"><span class="label">Rank:</span> {row["rank"]}</div>'

    if row['status']:
        html += f'<div class="info"><span class="label">Status:</span> {row["status"]}</div>'

    if row['dataset']:
        html += f'<div class="info"><span class="label">Dataset:</span> {row["dataset"]}</div>'

    if row['source_id']:
        html += f'<div class="info"><span class="label">Source ID:</span> {row["source_id"]}</div>'

    html += f'<div class="info"><span class="label">Database ID:</span> {row["id"]}</div>'

    if children_count > 0:
        html += f'<div class="info"><span class="label">Children:</span> {children_count}</div>'

    if parents:
        html += '<div class="lineage"><span class="label">Lineage:</span>'
        for parent in parents:
            html += f'<div class="lineage-item">{parent["rank"] or "?"}: <span class="scientific">{parent["name"]}</span></div>'
        html += '</div>'

    html += '''
    </body>
    </html>
    '''

    return html


@app.route('/health')
def health():
    """Health check endpoint."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) as count FROM taxa')
        count = cur.fetchone()['count']
        conn.close()
        return jsonify({
            'status': 'healthy',
            'taxa_count': count
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


if __name__ == '__main__':
    print(f"Starting {SERVICE_NAME}")
    print(f"Reconciliation endpoint: http://localhost:5000/reconcile")
    print(f"Add this URL to OpenRefine as a reconciliation service")
    app.run(debug=True, host='0.0.0.0', port=5000)
