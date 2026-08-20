"""
AeroDataBox API client for Air Tracker.

Responsibilities:
- Make AeroDataBox / RapidAPI requests
- Handle HTTP errors
- Handle HTTP 429 rate limits safely
- Use ICAO airport codes from the central configuration
- Keep API-specific endpoint handling in one place

The project configuration now uses ICAO airport codes such as:
KATL, EGLL, KLAX, EDDF, OMDB, WSSS, RJTT, YSSY,
VIDP, VOBL, BIKF, CYZF.
"""

import time

import requests

from config import (
    API_HOST,
    HEADERS,
    REQUEST_DELAY,
)


BASE_URL = f"https://{API_HOST}"

if not HEADERS.get("x-rapidapi-key"):
    print("[WARNING] AERODATABOX_KEY/API_KEY is empty. API calls will fail authentication.")


# ================================================================
# RATE LIMIT EXCEPTION
# ================================================================

class APIRateLimitError(Exception):
    """Raised when AeroDataBox/RapidAPI returns HTTP 429."""

    pass


# ================================================================
# GENERIC GET REQUEST
# ================================================================

def _get(path: str, params: dict | None = None):
    """
    Make one GET request to AeroDataBox.

    Returns:
        dict/list:
            Successful JSON response.

        None:
            Non-429 HTTP/API failure.

    Raises:
        APIRateLimitError:
            When HTTP 429 is received.
    """

    url = f"{BASE_URL}{path}"

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=20,
        )

        # --------------------------------------------------------
        # RATE LIMIT
        # --------------------------------------------------------

        if response.status_code == 429:

            print()
            print("=" * 65)
            print("[API RATE LIMIT] HTTP 429 received.")
            print("API quota/rate limit has been reached.")
            print("Stopping further API requests safely.")
            print("=" * 65)
            print()

            raise APIRateLimitError(
                "AeroDataBox API rate limit/quota reached."
            )

        # --------------------------------------------------------
        # OTHER HTTP ERRORS
        # --------------------------------------------------------

        if not response.ok:

            print(
                f"[HTTP ERROR] {url} -> "
                f"{response.status_code} "
                f"| body: {response.text[:500]}"
            )

            return None

        # --------------------------------------------------------
        # JSON RESPONSE
        # --------------------------------------------------------

        try:

            return response.json()

        except ValueError:

            print(
                f"[API ERROR] Invalid JSON response from {url}"
            )

            return None

    except APIRateLimitError:
        raise

    except requests.exceptions.Timeout:

        print(
            f"[REQUEST ERROR] Timeout: {url}"
        )

        return None

    except requests.exceptions.RequestException as e:

        print(
            f"[REQUEST ERROR] {url} -> {e}"
        )

        return None

    finally:

        # Respect the configured request delay.
        time.sleep(REQUEST_DELAY)


# ================================================================
# AIRPORT DETAILS
# ================================================================

def get_airport_info(
    icao_code: str,
):
    """
    Fetch airport information using an ICAO code.
    """

    return _get(
        f"/airports/icao/{icao_code}"
    )


def get_airport_iata(
    icao_code: str,
):
    """
    Resolve an ICAO airport code to its IATA code.
    """

    data = get_airport_info(
        icao_code
    )

    if not data:
        return None

    return data.get("iata")


def get_airport_info_by_iata(
    iata_code: str,
):
    """
    Fetch airport information using an IATA code.

    Used to backfill details (country, in particular) for
    airports that only ever show up as a flight origin/destination
    rather than one of the monitored AIRPORT_CODES — those are
    stored as stub rows by ensure_airport_stub() and never go
    through get_airport_info(), since that only ever gets called
    for the monitored ICAO list.
    """

    return _get(
        f"/airports/iata/{iata_code}"
    )

# ================================================================
# AIRPORT FLIGHTS
# ================================================================

def get_airport_flights(
    icao_code: str,
    from_local: str,
    to_local: str,
):
    """
    Fetch departures and arrivals for an airport.

    The monitored-airport configuration uses ICAO codes,
    therefore the ICAO airport endpoint is used here.

    The returned flight objects are passed unchanged to
    extract_data.py, where they are normalized into the
    database's IATA-based flight schema.
    """

    params = {
        "withLeg": "true",
        "direction": "Both",
        "withCancelled": "true",
        "withCodeshared": "true",
        "withCargo": "false",
        "withPrivate": "false",
    }

    return _get(
        f"/flights/airports/icao/"
        f"{icao_code}/{from_local}/{to_local}",
        params,
    )


# ================================================================
# AIRCRAFT DETAILS
# ================================================================

def get_aircraft_info(
    registration: str,
):
    """
    Fetch aircraft information by registration.
    """

    return _get(
        f"/aircrafts/reg/{registration}"
    )


def get_aircraft_info_safe(
    registration: str,
):
    """
    Fetch aircraft information without allowing an API
    rate-limit exception to crash the caller.

    Returns:
        (data, rate_limited)
    """

    try:

        data = get_aircraft_info(
            registration
        )

        return data, False

    except APIRateLimitError:

        return None, True


# ================================================================
# AIRPORT DELAY STATISTICS
# ================================================================

def get_airport_delays(
    icao_code: str,
):
    """
    Fetch AeroDataBox statistical delay information
    using the monitored airport's ICAO code.

    IMPORTANT:
        fetch_delays.py still calculates the final delay
        metrics from our own flights table. This endpoint
        is used to determine whether live delay information
        is available for the airport.
    """

    return _get(
        f"/airports/icao/{icao_code}/delays"
    )