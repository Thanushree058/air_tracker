"""
Central configuration for Air Tracker.
"""

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv


# ================================================================
# LOAD .ENV
# ================================================================

load_dotenv(override=True)


# ================================================================
# AERODATABOX API
# ================================================================

API_HOST = "aerodatabox.p.rapidapi.com"

API_KEY = os.environ.get(
    "AERODATABOX_KEY",
    os.environ.get("API_KEY", "")
)

HEADERS = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": API_HOST,
}


# ================================================================
# MONITORED AIRPORTS
# ================================================================
#
# 12 airports selected for the Air Tracker project.
#
# Mix of North America, Europe, Middle East, Asia and Australia.
#
# CYZF (Yellowknife) has been replaced with
# LEMD (Madrid-Barajas) because AeroDataBox does not provide
# live delay information for CYZF.
# ================================================================

AIRPORTS = [
    "KATL",  # Atlanta
    "EGLL",  # London Heathrow
    "KLAX",  # Los Angeles
    "EDDF",  # Frankfurt
    "OMDB",  # Dubai
    "WSSS",  # Singapore
    "RJTT",  # Tokyo Haneda
    "YSSY",  # Sydney
    "VIDP",  # Delhi
    "VOBL",  # Bengaluru
    "BIKF",  # Keflavik
    "LEMD",  # Madrid-Barajas
]


# ================================================================
# BACKWARDS COMPATIBILITY
# ================================================================

# Existing project files currently import AIRPORT_CODES.
AIRPORT_CODES = AIRPORTS


# ================================================================
# FLIGHT FETCH SETTINGS
# ================================================================

DAYS_TO_FETCH = int(
    os.environ.get("DAYS_TO_FETCH", "2")
)

START_DATE = (
    datetime.now() - timedelta(days=DAYS_TO_FETCH)
).strftime("%Y-%m-%d")

DAYS_BACK = DAYS_TO_FETCH


# ================================================================
# OPTIONAL API FETCHES
# ================================================================

FETCH_AIRPORT_DETAILS = (
    os.environ.get("FETCH_AIRPORT_DETAILS", "1") == "1"
)

FETCH_AIRCRAFT_DETAILS = (
    os.environ.get("FETCH_AIRCRAFT_DETAILS", "1") == "1"
)

# NOTE: aircraft.model must be populated for aircraft.model to be
# non-NULL, which several of the required analysis queries (1, 2,
# 6, 9, 10) depend on for meaningful output. fetch_and_store_aircraft()
# only calls the API for the top AIRCRAFT_FETCH_BATCH_SIZE
# highest-flight-count registrations per run (see extract_data.py),
# so this can be left on across several runs without a large quota
# hit — set FETCH_AIRCRAFT_DETAILS=0 in your environment only if you
# need to conserve API calls for something else.

SKIP_FLIGHTS = False

# ================================================================
# AIRCRAFT FETCH BATCH SIZE
# ================================================================
#
# How many not-yet-fetched aircraft registrations (ordered by
# flight_count DESC, flight_count >= 5) fetch_and_store_aircraft()
# will call the API for on a single run.
#
# With ~12 monitored airports over a couple of days, the number of
# distinct registrations with >=5 flights can run into the low
# thousands, so the previous hardcoded value of 20 meant queries
# 1, 2, 6, 9 and 10 would show mostly NULL models for a very long
# time (100+ runs) before the aircraft table was reasonably
# complete. Raise/lower this to trade off API quota usage per run
# against how many runs are needed before those queries look
# meaningful. Each aircraft is one API call, so keep this within
# whatever your AeroDataBox/RapidAPI plan allows per run.
AIRCRAFT_FETCH_BATCH_SIZE = int(
    os.environ.get("AIRCRAFT_FETCH_BATCH_SIZE", "300")
)


# ================================================================
# STUB AIRPORT FETCH BATCH SIZE
# ================================================================
#
# Airports that only ever appear as a flight origin/destination
# (never one of the monitored AIRPORT_CODES) are stored as stub
# rows with country = NULL, because fetch_and_store_airports()
# only calls the airport-details endpoint for the monitored list.
#
# Query 5 in analysis_queries.sql labels a flight 'Unknown'
# whenever either endpoint's country isn't known, so with a large
# flight dataset most flights show 'Unknown' until these stubs are
# backfilled. fetch_and_store_stub_airport_details() resolves up
# to this many of the most-referenced unresolved airports per run
# (one API call each), so raise/lower it to trade off API quota
# per run against how many runs it takes for query 5 to stop
# showing 'Unknown' for most flights.
STUB_AIRPORT_FETCH_BATCH_SIZE = int(
    os.environ.get("STUB_AIRPORT_FETCH_BATCH_SIZE", "300")
)


# ================================================================
# API SAFETY
# ================================================================

REQUEST_DELAY = float(
    os.environ.get("REQUEST_DELAY", "1.0")
)

# Stop further API requests after a rate-limit response.
STOP_ON_429 = True


# ================================================================
# MYSQL
# ================================================================

DB_HOST = os.environ.get(
    "DB_HOST",
    "localhost"
)

DB_PORT = int(
    os.environ.get(
        "DB_PORT",
        "3306"
    )
)

DB_USER = os.environ.get(
    "DB_USER",
    "root"
)

DB_PASSWORD = os.environ.get(
    "DB_PASSWORD",
    ""
)

DB_NAME = os.environ.get(
    "DB_NAME",
    "air_tracker_final"
)


# ================================================================
# BACKWARDS COMPATIBILITY
# ================================================================

DB_PATH = DB_NAME