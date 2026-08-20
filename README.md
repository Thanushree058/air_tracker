# Air Tracker: Flight Analytics

End-to-end pipeline: AeroDataBox API → MySQL → SQL analysis → Streamlit dashboard.

## 0. Folder layout

```
air_tracker/
├── requirements.txt
├── config.py                     # API key, monitored airports, DB settings (edit this)
├── schema.sql                    # table definitions
├── api_client.py                 # thin wrapper around AeroDataBox endpoints
├── db_manager.py                 # MySQL connection + insert/upsert helpers
├── extract_data.py               # run this to populate the database
├── fetch_delays.py               # standalone delay-stats fetch (also called by extract_data.py)
├── check_corruption_count.sql    # one-off cleanup for a specific bad-row pattern — see "Maintenance" below
├── check_arrival_before_departure.sql  # cleanup for scheduled_arrival predating scheduled_departure — see "Maintenance" below
├── analysis_queries.sql          # the 11 required analysis queries
├── run_queries.py                # executes analysis_queries.sql, prints/saves results
└── app.py                        # Streamlit dashboard
```

There is no `air_tracker.db` file — all data lives in a MySQL database (default name `air_tracker`, set via `DB_NAME` in `config.py` / the `DB_*` environment variables).

## 1. Get your AeroDataBox API key

1. Sign up on RapidAPI: https://rapidapi.com/aedbx-aedbx/api/aerodatabox
2. Subscribe to the free tier.
3. Copy your `x-rapidapi-key`.
4. Set it as the `AERODATABOX_KEY` environment variable — never commit a real key to GitHub. `config.py` reads it via `os.environ.get("AERODATABOX_KEY", "your_api_key_here")`.

## 2. Install dependencies

```bash
pip install -r requirements.txt --break-system-packages
```

You'll also need `mysql-connector-python` (used by `db_manager.py`) and a running MySQL server.

## 3. Configure MySQL and your airports

Set these via environment variables (or edit the defaults in `config.py`):

```
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=<your password>
DB_NAME=air_tracker
```

Edit `AIRPORTS` in `config.py` to pick your 10–15 airport codes, e.g.:
```python
AIRPORTS = ["DEL", "BOM", "BLR", "MAA", "HYD", "CCU", "GOI", "PNQ",
            "AMD", "COK", "JAI", "LKO"]
```

## 4. Build the database

```bash
python extract_data.py
```
This will, in order:
1. Create the `air_tracker` MySQL database and tables from `schema.sql` if they don't already exist (`db_manager.init_db`).
2. Fetch airport details for each IATA code → `airport` table.
3. Fetch arrivals + departures for each monitored airport over the last `DAYS_TO_FETCH` days, in resumable time windows (tracked in `fetched_windows`) → `flights` table.
4. Collect the unique aircraft registrations seen in `flights`, fetch each aircraft's details → `aircraft` table.
5. Fetch delay statistics per airport, with avg/median delay minutes computed locally from actual vs. scheduled flight times → `airport_delays` table.

It's rate-limit aware (small sleep between calls, backs off cleanly on HTTP 429) and wraps every API call in try/except so one bad airport code doesn't kill the whole run. If a run is interrupted or hits a quota limit partway through, re-running `extract_data.py` resumes from where it left off instead of re-fetching everything.

## 5. Run the analysis queries

```bash
python run_queries.py
```
This executes all 11 queries from `analysis_queries.sql` against the `air_tracker` MySQL database and prints each result as a table (also saved to `query_results.txt`).

## 6. Launch the dashboard

```bash
streamlit run app.py
```
Gives you: homepage KPIs, flight search/filter, airport details viewer, delay analysis charts, and route leaderboards — all backed by live SQL queries against the database.

## 7. Maintenance

A handful of one-off scripts were used during development to clean up data-quality issues (reused/malformed `flight_id` schemes, rows split across the departures/arrivals API calls with only one side of the route filled in, and duplicate rows from before those bugs were fixed). They aren't part of this delivery since a fresh `extract_data.py` run against the current schema shouldn't reproduce those issues — the fixes they addressed are already reflected in `extract_data.py`/`db_manager.py` as they stand now.

One targeted cleanup script is still included: `check_corruption_count.sql` removes flight rows where `origin_iata` equals `destination_iata` (a small number of provably-corrupted rows, ~0.6% of the dataset at last check). Run its `SELECT COUNT(*)` sanity check first to confirm the count matches what you expect before running the `DELETE`.

A second targeted cleanup, `check_arrival_before_departure.sql`, clears `scheduled_arrival` on rows where it falls before `scheduled_departure` (same underlying cause as the reused-flight-number delay outliers `fetch_delays.py` already filters — see that script's own header comment for the full explanation). It only nulls the one bad column, not the whole row.

If you also want `airport_delays` fully consistent with a just-cleaned `flights` table, the script's trailing comment shows how to clear and recompute it (`TRUNCATE TABLE airport_delays;` then `python fetch_delays.py`) — no API cost, since `fetch_delays.py` derives its counts and delay minutes from `flights` directly and only calls the AeroDataBox `/delays` endpoint per airport to check whether live delay data exists for it (see that script's docstrings for the full reasoning: timezone normalization, why counts are sourced locally, and why very small samples are stored as `NULL` instead of a guessed average).

## 8. Before pushing to GitHub

- Confirm no real API key or database password is hardcoded anywhere (`config.py` and `db_manager.py` should only read from environment variables — double-check any one-off scripts you added).
- Add a `.env` file (if you use one) to `.gitignore`.
- Include: all `.py` files, `check_corruption_count.sql`, `check_arrival_before_departure.sql`, `schema.sql`, `analysis_queries.sql`, `requirements.txt`, this `README.md`, and a document with all SQL queries + sample output (the assignment explicitly asks for this — `query_results.txt`, generated by `run_queries.py`, is that document; make sure `.gitignore` doesn't exclude it).