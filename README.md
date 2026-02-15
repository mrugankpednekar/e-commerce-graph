# E-Commerce Relationship Graph (Rebuilt)

Fresh rebuild with:
- `.venv`-based Python runtime,
- LLM-powered relationship discovery (Cerebras),
- async refresh API with live run logs,
- interactive graph UI with node search.

## 1) Setup venv

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2) Configure API key

```bash
export CEREBRAS_API_KEY="your_key_here"
```

If you want persistence across terminals (zsh):

```bash
echo 'export CEREBRAS_API_KEY="your_key_here"' >> ~/.zshrc
source ~/.zshrc
```

## 3) Run app

```bash
./scripts/run_ui.sh 8080
```

Open:
- `http://localhost:8080`

## How refresh works

- Click **Refresh with LLM** in the UI.
- Backend starts a background refresh job.
- UI polls `/api/refresh_status` every 1.5s and streams log output.
- New relationships and discovered nodes are persisted.

## Data files

- `data/latest_relationships.json`
- `data/latest_nodes.json`
- `data/search_history.jsonl` (every query + fetch event)
- `data/persistent_state.json` (known nodes + seen URLs cache)
- `data/runtime/refresh.log` (live backend logs)
- `data/snapshots/relationships_*.json`

## Low-credit defaults

Refresh defaults are intentionally constrained:
- `days=120`
- `max_per_query=4`
- `expansion_rounds=1`
- `max_queries_per_node=2`
- `model=llama3.1-8b`

# Self-Updating E-Commerce Relationship Graph

This project now includes an automated updater that:
- starts from `major_companies.txt`,
- uses an LLM to generate search queries per company node,
- traverses discovered nodes to find additional connections and companies,
- uses an LLM to extract only explicit, source-backed relationship edges,
- writes an updated edge list and graph on every run.

## Files

- `major_companies.txt`: companies to monitor (edit this list anytime).
- `update_relationship_graph.py`: LLM-first traversal/updater script.
- `data/latest_relationships.csv`: latest extracted edges.
- `data/latest_relationships.json`: latest extracted edges in JSON.
- `data/latest_nodes.json`: all current graph nodes (seed + discovered).
- `data/snapshots/`: timestamped historical CSV snapshots.
- `data/search_history.jsonl`: persistent log of every generated search query and fetch result.
- `data/persistent_state.json`: persistent memory (known nodes + seen article URLs).
- `data/runtime/refresh.log`: live backend refresh log shown in UI.

## Run Once

```bash
pip install cerebras-cloud-sdk
CEREBRAS_API_KEY=your_key_here python3 update_relationship_graph.py
```

Recommended for broader coverage:

```bash
CEREBRAS_API_KEY=your_key_here python3 update_relationship_graph.py --days 365 --max-per-query 8 --expansion-rounds 2 --max-queries-per-node 4
```

## Make It Self-Updating (macOS launchd)

1. One-command install:

```bash
./scripts/install_launchd.sh
```

2. Or manual install (if preferred):

```bash
cp scripts/com.ecommerce.graph.update.plist ~/Library/LaunchAgents/
```

3. Edit paths inside the copied plist:
- Replace `__WORKSPACE__` with your absolute workspace path.
- Replace `__PYTHON3__` with output of `which python3`.

4. Load it:

```bash
launchctl unload ~/Library/LaunchAgents/com.ecommerce.graph.update.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.ecommerce.graph.update.plist
launchctl start com.ecommerce.graph.update
```

By default, it runs every 2 hours and logs to:
- `logs/update.out.log`
- `logs/update.err.log`

## Interactive UI Dashboard (Graph-first)

The UI is intentionally minimal and sleek:
- graph is the main component,
- in-app company search (`Find company...`) focuses the matching node,
- click an edge to view its source list,
- "Refresh with LLM" button runs a fresh traversal + extraction and updates the graph,
- every company in the graph dataset is rendered as a node (including companies without current edges).
- refresh status + live logs are visible in the app while the job runs.

Run locally:

```bash
export CEREBRAS_API_KEY=your_key_here
./scripts/run_ui.sh 8080
```

Then open:

```text
http://localhost:8080/ui/
```

The refresh endpoint uses your local environment variable:
- `CEREBRAS_API_KEY`

## Notes

- `CEREBRAS_API_KEY` is required for updates/refresh.
- Add/remove seeds in `major_companies.txt` to control graph scope.
- Refresh runs with bounded defaults to avoid timeouts (`days=120`, `max-per-query=4`, `rounds=1`, `queries-per-node=2`, model `llama3.1-8b`).
