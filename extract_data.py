"""
Air Tracker ETL extraction pipeline.

Steps:
    1. Fetch/store airport details
    2. Fetch/store flight data
    3. Fetch/store aircraft details
    4. Fetch/store delay statistics

IMPORTANT CODE ARCHITECTURE:

config.py contains monitored AIRPORT_CODES as ICAO codes:

    KATL, EGLL, KLAX, EDDF, ...

AeroDataBox API calls use those airport codes.

The database, however, stores airport_delays.airport_iata
as an IATA code:

    KATL -> ATL
    EGLL -> LHR
    KLAX -> LAX

Therefore delay processing explicitly converts:

    ICAO -> IATA

before interacting with airport_delays.

This prevents the MySQL foreign-key error:

    Cannot add or update a child row: a foreign key constraint fails
"""


from datetime import datetime, timedelta
import json
import re
import sys

import api_client
import db_manager as db

from config import (
    AIRPORT_CODES,
    DAYS_BACK,
    DB_NAME,
    SKIP_FLIGHTS,
    FETCH_AIRPORT_DETAILS,
    FETCH_AIRCRAFT_DETAILS,
    AIRCRAFT_FETCH_BATCH_SIZE,
    STUB_AIRPORT_FETCH_BATCH_SIZE,
)


APIRateLimitError = api_client.APIRateLimitError


# ================================================================
# TIME WINDOWS
# ================================================================

def iter_time_windows(days_back: int):
    """
    Generate stable 12-hour API windows.

    The end time is rounded up to the next full hour so that
    repeated runs use identical window boundaries.

    This allows fetched_windows to correctly prevent duplicate
    API requests.
    """

    now = datetime.utcnow()

    end = (
        now + timedelta(hours=1)
    ).replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    start_bound = (
        end - timedelta(days=days_back)
    )

    current = end

    while current > start_bound:

        window_start = max(
            current - timedelta(hours=12),
            start_bound,
        )

        yield (
            window_start.strftime(
                "%Y-%m-%dT%H:%M"
            ),
            current.strftime(
                "%Y-%m-%dT%H:%M"
            ),
        )

        current = window_start


# ================================================================
# SAFE VALUE HELPER
# ================================================================

def get_value(value, key=None):
    """
    Safely extract a scalar value from a possible dictionary.
    """

    if isinstance(value, dict):

        if key:
            return value.get(key)

        return None

    return value


# ================================================================
# AIRPORT PARSER
# ================================================================

def parse_airport(
    raw: dict,
    iata_code: str,
) -> dict:

    if not isinstance(raw, dict):

        return {
            "icao_code": None,
            "iata_code": iata_code,
            "name": iata_code,
            "city": None,
            "country": None,
            "continent": None,
            "latitude": None,
            "longitude": None,
            "timezone": None,
        }

    country = raw.get("country")
    location = raw.get("location")
    continent = raw.get("continent")
    timezone = raw.get("timeZone")

    if isinstance(country, dict):

        country = (
            country.get("name")
            or country.get("code")
        )

    latitude = None
    longitude = None

    if isinstance(location, dict):

        latitude = location.get("lat")
        longitude = location.get("lon")

    if isinstance(continent, dict):

        continent = (
            continent.get("name")
            or continent.get("code")
        )

    if isinstance(timezone, dict):

        timezone = (
            timezone.get("name")
            or timezone.get("id")
        )

    return {
        "icao_code": raw.get("icao"),

        "iata_code": (
            raw.get("iata")
            or iata_code
        ),

        "name": (
            raw.get("fullName")
            or raw.get("shortName")
            or raw.get("name")
        ),

        "city": (
            raw.get("municipalityName")
            or raw.get("city")
        ),

        "country": country,

        "continent": continent,

        "latitude": latitude,

        "longitude": longitude,

        "timezone": timezone,
    }


# ================================================================
# DATETIME CLEANING
# ================================================================

def clean_datetime(value):
    """
    Convert AeroDataBox datetime strings into MySQL-compatible
    DATETIME strings.

    Examples:

        2026-08-13T01:03+05:30
        2026-08-12T11:55-04:00
        2026-08-12T11:55Z

    become:

        2026-08-13 01:03:00
        2026-08-12 11:55:00
        2026-08-12 11:55:00
    """

    if not value:
        return None

    try:

        value = str(value)

        value = re.sub(
            r"[+-]\d{2}:\d{2}$",
            "",
            value,
        )

        value = value.rstrip("Z")

        value = value.replace(
            "T",
            " ",
        )

        value = value.strip()

        if len(value) == 16:
            value += ":00"

        return value

    except Exception:

        return None


# ================================================================
# SCHEDULED DEPARTURE
# ================================================================

def get_scheduled_departure(departure):
    """
    Bugfix: UTC is preferred over local. scheduled_departure and
    scheduled_arrival come from two different airports (origin vs
    destination), which can be in different timezones. If each is
    stored in its own airport's local time, direct comparisons
    (arrival vs departure, or actual vs scheduled) mix two
    different time bases and produce bogus results - e.g. an
    arrival that looks earlier than its departure, or a delay of
    ~5-6 hours that's really just a timezone offset. UTC is the
    same clock everywhere, so it is the only safe basis for any
    arithmetic on these fields. Local time is not stored here; if
    it's needed for display later, store it in a separate column
    instead of using it in place of UTC.
    """

    scheduled = (
        departure.get("scheduledTime")
        or {}
    )

    if not isinstance(
        scheduled,
        dict,
    ):
        return None

    return clean_datetime(
        scheduled.get("utc")
        or scheduled.get("local")
    )


# ================================================================
# SCHEDULED ARRIVAL
# ================================================================

def get_scheduled_arrival(arrival):
    """
    Bugfix: UTC preferred over local - see get_scheduled_departure()
    for why mixing local times across two different airports breaks
    arrival-vs-departure and delay-minute arithmetic.
    """

    scheduled = (
        arrival.get("scheduledTime")
        or {}
    )

    if not isinstance(
        scheduled,
        dict,
    ):
        return None

    return clean_datetime(
        scheduled.get("utc")
        or scheduled.get("local")
    )


# ================================================================
# ACTUAL DEPARTURE
# ================================================================

def get_actual_departure(departure):
    """
    Bugfix: AeroDataBox has no "actualTime" field. A confirmed
    actual departure event is reported under "runwayTime" (only
    present once the flight has actually pushed back/taken off).
    "revisedTime" is a different thing - an updated ESTIMATE used
    for delay prediction, not a confirmed actual - so it is
    intentionally not used here to avoid mislabeling estimates as
    actuals.

    Bugfix: UTC preferred over local - see get_scheduled_departure()
    for why. This one matters even more for delay math: if
    scheduled_departure and actual_departure ever ended up on
    different time bases (e.g. one record has both local/utc but
    another only returns utc for that particular field), diffing
    them produces a delay that's really just a timezone offset.
    Using UTC consistently for both eliminates that failure mode.
    """

    actual = (
        departure.get("runwayTime")
        or departure.get("actualTime")
        or {}
    )

    if not isinstance(
        actual,
        dict,
    ):
        return None

    return clean_datetime(
        actual.get("utc")
        or actual.get("local")
    )


# ================================================================
# ACTUAL ARRIVAL
# ================================================================

def get_actual_arrival(arrival):
    """
    Bugfix: see get_actual_departure() - AeroDataBox reports the
    confirmed actual arrival (landing) event under "runwayTime",
    not "actualTime". UTC is preferred over local for the same
    reason as get_actual_departure().
    """

    actual = (
        arrival.get("runwayTime")
        or arrival.get("actualTime")
        or {}
    )

    if not isinstance(
        actual,
        dict,
    ):
        return None

    return clean_datetime(
        actual.get("utc")
        or actual.get("local")
    )


# ================================================================
# FIX OVERNIGHT ARRIVAL
# ================================================================

def fix_scheduled_arrival(
    scheduled_departure,
    scheduled_arrival,
):
    """
    Correct an arrival that appears earlier than departure because
    the flight crosses midnight.

    NOTE: now that get_scheduled_departure()/get_scheduled_arrival()
    prefer UTC over local, both timestamps share one consistent time
    base, so this function should trigger far less often than before
    (it no longer has to work around origin-local vs destination-local
    mismatches - only genuine same-UTC-day edge cases from the API).
    Kept as a safety net rather than removed outright.

    IMPORTANT (bugfix):
    This only kicks in when arrival < departure - i.e. AeroDataBox
    gave a bare time-of-day that landed on the same calendar date
    as departure by mistake. If arrival is already >= departure,
    the API has already given a full, correctly-ordered date for
    both fields, and that is trusted as-is no matter how long the
    scheduled duration looks (some listings legitimately span more
    than 24h - long-haul with a technical stop, schedule data for
    connecting legs, etc.). The previous version re-validated
    already-valid dates against a 24h cap and nulled out perfectly
    good arrival times whenever that cap was exceeded.

    Only a genuine same-day-appears-earlier case is corrected, and
    only rejected outright if it's still impossible after adding a
    day.
    """

    if not scheduled_departure:
        return scheduled_arrival

    if not scheduled_arrival:
        return scheduled_arrival

    try:

        departure = datetime.strptime(
            scheduled_departure,
            "%Y-%m-%d %H:%M:%S",
        )

        arrival = datetime.strptime(
            scheduled_arrival,
            "%Y-%m-%d %H:%M:%S",
        )

        if arrival >= departure:

            # Already a full, correctly-ordered date pair from the
            # API - trust it as given, regardless of duration.
            return scheduled_arrival

        # arrival < departure: genuine midnight-rollover case.
        corrected_arrival = (
            arrival + timedelta(days=1)
        )

        duration = (
            corrected_arrival - departure
        ).total_seconds() / 3600

        if 0 <= duration <= 24:

            return corrected_arrival.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        print(
            "[TIME WARNING] "
            f"Invalid scheduled times: "
            f"{scheduled_departure} -> "
            f"{scheduled_arrival}"
        )

        return None

    except Exception as e:

        print(
            "[TIME WARNING] "
            f"Could not fix arrival: {e}"
        )

        return scheduled_arrival


# ================================================================
# FLIGHT PARSER
# ================================================================

def parse_flight(
    flight,
    known_airport_iata=None,
    list_type=None,
):
    """
    Convert one AeroDataBox flight object into the flights table
    format.
    """

    if not isinstance(
        flight,
        dict,
    ):
        return None

    try:

        departure = (
            flight.get("departure")
            or {}
        )

        arrival = (
            flight.get("arrival")
            or {}
        )

        aircraft = (
            flight.get("aircraft")
            or {}
        )

        airline = (
            flight.get("airline")
            or {}
        )

        departure_airport = (
            departure.get("airport")
            or {}
        )

        arrival_airport = (
            arrival.get("airport")
            or {}
        )

        # --------------------------------------------------------
        # FLIGHT NUMBER
        # --------------------------------------------------------

        flight_number = (
            flight.get("number")
            or flight.get("flightNumber")
        )

        if not flight_number:
            return None

        flight_number = str(
            flight_number
        ).strip()

        if not flight_number:
            return None

        # --------------------------------------------------------
        # ORIGIN
        # --------------------------------------------------------

        origin_iata = None

        if isinstance(
            departure_airport,
            dict,
        ):

            origin_iata = (
                departure_airport.get("iata")
            )

        # --------------------------------------------------------
        # DESTINATION
        # --------------------------------------------------------

        destination_iata = None

        if isinstance(
            arrival_airport,
            dict,
        ):

            destination_iata = (
                arrival_airport.get("iata")
            )

        # --------------------------------------------------------
        # BACKFILL ENDPOINT AIRPORT
        # --------------------------------------------------------

        if known_airport_iata:

            if (
                list_type == "departures"
                and not origin_iata
            ):

                origin_iata = (
                    known_airport_iata
                )

            elif (
                list_type == "arrivals"
                and not destination_iata
            ):

                destination_iata = (
                    known_airport_iata
                )

        # --------------------------------------------------------
        # TIMES
        # --------------------------------------------------------

        scheduled_departure = (
            get_scheduled_departure(
                departure
            )
        )

        scheduled_arrival = (
            get_scheduled_arrival(
                arrival
            )
        )

        scheduled_arrival = (
            fix_scheduled_arrival(
                scheduled_departure,
                scheduled_arrival,
            )
        )

        actual_departure = (
            get_actual_departure(
                departure
            )
        )

        actual_arrival = (
            get_actual_arrival(
                arrival
            )
        )

        # --------------------------------------------------------
        # FLIGHT ID
        # --------------------------------------------------------

        day = (
            scheduled_departure
            or actual_departure
            or scheduled_arrival
            or actual_arrival
        )

        day = (
            day[:10]
            if day
            else "NA"
        )

        flight_id = (
            f"{flight_number}_{day}"
        )

        # --------------------------------------------------------
        # AIRCRAFT
        # --------------------------------------------------------

        aircraft_registration = None

        if isinstance(
            aircraft,
            dict,
        ):

            aircraft_registration = (
                aircraft.get("reg")
            )

        # --------------------------------------------------------
        # AIRLINE
        # --------------------------------------------------------

        airline_code = None

        if isinstance(
            airline,
            dict,
        ):

            airline_code = (
                airline.get("iata")
                or airline.get("icao")
            )

        if not airline_code:

            # Fallback: AeroDataBox sometimes omits the whole
            # "airline" object on sparse codeshare listings, even
            # though the flight number's own prefix already encodes
            # the carrier code (e.g. "JL 7750" -> "JL").
            prefix_match = re.match(
                r"^([A-Z0-9]{2})\s*\d",
                flight_number.upper(),
            )

            if prefix_match:

                airline_code = (
                    prefix_match.group(1)
                )

        # --------------------------------------------------------
        # STATUS
        # --------------------------------------------------------

        status = flight.get("status")

        return {
            "flight_id": str(
                flight_id
            ),

            "flight_number": flight_number,

            "aircraft_registration":
                aircraft_registration,

            "origin_iata":
                origin_iata,

            "destination_iata":
                destination_iata,

            "scheduled_departure":
                scheduled_departure,

            "actual_departure":
                actual_departure,

            "scheduled_arrival":
                scheduled_arrival,

            "actual_arrival":
                actual_arrival,

            "status":
                status,

            "airline_code":
                airline_code,
        }

    except Exception as e:

        print(
            "[PARSE WARNING] "
            f"Skipped a flight record: {e}"
        )

        return None


# ================================================================
# AIRCRAFT PARSER
# ================================================================

def parse_aircraft(
    raw,
    registration,
):

    if not isinstance(
        raw,
        dict,
    ):
        return None

    owner = raw.get("owner")

    if isinstance(
        owner,
        dict,
    ):

        owner = (
            owner.get("name")
            or owner.get("operatorName")
        )

    model = raw.get("model")

    if isinstance(
        model,
        dict,
    ):

        model = (
            model.get("name")
            or model.get("code")
        )

    manufacturer = raw.get(
        "manufacturer"
    )

    if isinstance(
        manufacturer,
        dict,
    ):

        manufacturer = (
            manufacturer.get("name")
            or manufacturer.get("code")
        )

    return {
        "registration":
            raw.get("reg")
            or registration,

        "model":
            model,

        "manufacturer":
            manufacturer,

        "icao_type_code":
            raw.get("typeCode"),

        "owner":
            owner,
    }


# ================================================================
# AIRCRAFT API DIAGNOSTIC
# ================================================================
#
# Standalone debug helper - run with:
#
#     python extract_data.py --debug-aircraft [REGISTRATION]
#
# Calls the AeroDataBox aircraft endpoint directly for ONE
# registration (bypassing the whole ETL loop) and prints:
#   - the raw JSON AeroDataBox returned
#   - what parse_aircraft() extracted from it
#
# Use this when aircraft.model keeps coming back NULL - it tells
# you immediately whether the problem is a rate limit/quota issue,
# an auth issue, or a field-name mismatch against the raw response.
# ================================================================

def debug_aircraft_api(
    registration: str = None,
):

    if not registration:

        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT aircraft_registration, COUNT(*) AS c
            FROM flights
            WHERE aircraft_registration IS NOT NULL
            GROUP BY aircraft_registration
            ORDER BY c DESC
            LIMIT 1
            """
        )

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        registration = row[0] if row else None

    if not registration:

        print(
            "No aircraft registration found/provided."
        )

        return

    print(
        f"Testing AeroDataBox aircraft endpoint for: {registration}"
    )

    print(
        f"API_HOST = {api_client.API_HOST}"
    )

    print(
        f"API key present: "
        f"{bool(api_client.HEADERS.get('x-rapidapi-key'))}"
    )

    print("-" * 65)

    try:

        raw = api_client.get_aircraft_info(
            registration
        )

    except APIRateLimitError as e:

        print(
            f"[RATE LIMITED] {e}"
        )

        print(
            "\n-> Your RapidAPI/AeroDataBox quota is exhausted.\n"
            "   Check usage at "
            "https://rapidapi.com/developer/billing\n"
            "   (or your AeroDataBox portal usage page) and "
            "either\n"
            "   wait for reset or upgrade the plan."
        )

        return

    print(
        "RAW RESPONSE:"
    )

    print(
        json.dumps(
            raw,
            indent=2,
            default=str,
        )
    )

    print("-" * 65)

    if raw is None:

        print(
            "-> _get() returned None: the request failed "
            "(non-429 HTTP error, bad JSON, or timeout).\n"
            "   Scroll up - api_client.py prints an [HTTP ERROR] "
            "or\n"
            "   [REQUEST ERROR] line right before this with the\n"
            "   real status code / body."
        )

        return

    parsed = parse_aircraft(
        raw,
        registration,
    )

    print(
        "PARSED RESULT (what would be written to the DB):"
    )

    print(
        json.dumps(
            parsed,
            indent=2,
            default=str,
        )
    )

    if parsed and parsed.get("model"):

        print(
            "\n-> SUCCESS: model extracted correctly."
        )

    else:

        print(
            "\n-> model is still empty. Compare the RAW RESPONSE "
            "keys above against parse_aircraft() - AeroDataBox "
            "may be using a different field name/shape than "
            "what's being read (e.g. 'model' nested differently, "
            "or a plan-tier restriction blanking that field)."
        )


# ================================================================
# FLIGHT TIME FIELDS DIAGNOSTIC
# ================================================================
#
# Standalone debug helper - run with:
#
#     python extract_data.py --debug-flight-times [ICAO_CODE]
#
# Fetches ONE short window for one monitored airport directly
# (bypassing the fetched_windows dedup, so it always makes a live
# call) and prints the raw departure/arrival timing objects plus
# what get_actual_departure()/get_actual_arrival() extract from
# them. Costs exactly 1 API call.
#
# Use this when avg_delay_min/median_delay_min keep coming back
# NULL with no [DELAY WARNING] line in the console - that silence
# means compute_delay_minutes() found ZERO rows with both a
# scheduled AND an actual timestamp, which usually means the
# actualTime field AeroDataBox returns doesn't match what
# get_actual_departure()/get_actual_arrival() are reading.
# ================================================================

def debug_flight_times(
    icao_code: str = None,
):

    if not icao_code:
        icao_code = AIRPORT_CODES[0]

    now = datetime.now()

    from_local = (
        now - timedelta(hours=6)
    ).strftime("%Y-%m-%dT%H:%M")

    to_local = now.strftime(
        "%Y-%m-%dT%H:%M"
    )

    print(
        f"Testing AeroDataBox flight timing fields for: "
        f"{icao_code}"
    )

    print(
        f"Window: {from_local} -> {to_local}"
    )

    print("-" * 65)

    try:

        data = api_client.get_airport_flights(
            icao_code,
            from_local,
            to_local,
        )

    except APIRateLimitError as e:

        print(
            f"[RATE LIMITED] {e}"
        )

        return

    if not data:

        print(
            "No data returned for this window - try a different "
            "airport or a wider window."
        )

        return

    departures = (
        data.get("departures")
        or []
    )

    arrivals = (
        data.get("arrivals")
        or []
    )

    print(
        f"Got {len(departures)} departures, "
        f"{len(arrivals)} arrivals."
    )

    sample = (
        departures[0]
        if departures
        else (
            arrivals[0]
            if arrivals
            else None
        )
    )

    if not sample:

        print(
            "Window had zero flights - try a different airport "
            "or a wider window."
        )

        return

    departure_obj = (
        sample.get("departure")
        or {}
    )

    arrival_obj = (
        sample.get("arrival")
        or {}
    )

    print(
        "RAW departure block:"
    )

    print(
        json.dumps(
            departure_obj,
            indent=2,
            default=str,
        )
    )

    print("-" * 65)

    print(
        "RAW arrival block:"
    )

    print(
        json.dumps(
            arrival_obj,
            indent=2,
            default=str,
        )
    )

    print("-" * 65)

    extracted = {
        "scheduled_departure": get_scheduled_departure(
            departure_obj
        ),
        "actual_departure": get_actual_departure(
            departure_obj
        ),
        "scheduled_arrival": get_scheduled_arrival(
            arrival_obj
        ),
        "actual_arrival": get_actual_arrival(
            arrival_obj
        ),
    }

    print(
        "EXTRACTED (what the current code reads out of the "
        "blocks above):"
    )

    print(
        json.dumps(
            extracted,
            indent=2,
            default=str,
        )
    )

    if (
        not extracted["actual_departure"]
        and not extracted["actual_arrival"]
    ):

        print(
            "\n-> Both actual_* fields are empty. Compare the RAW "
            "blocks above against get_actual_departure()/"
            "get_actual_arrival() in extract_data.py - look for "
            "whatever key AeroDataBox actually used for the real "
            "departure/arrival time (it may not be called "
            "'actualTime', or this flight simply hasn't happened "
            "yet - try a flight further in the past)."
        )

    else:

        print(
            "\n-> actual_* fields extracted correctly for this "
            "sample flight."
        )


# ================================================================
# FETCH ONE AIRPORT / WINDOW
# ================================================================

def fetch_airport_window(
    conn,
    airport,
    from_local,
    to_local,
    known_iata=None,
):

    if db.has_window_been_fetched(
        conn,
        airport,
        from_local,
        to_local,
    ):

        print(
            f"  = {airport} "
            f"[{from_local} -> {to_local}] "
            f"already fetched, skipping"
        )

        return [], True

    print(
        f"  + {airport} "
        f"[{from_local} -> {to_local}]"
    )

    try:

        data = (
            api_client.get_airport_flights(
                airport,
                from_local,
                to_local,
            )
        )

    except APIRateLimitError:

        raise

    except Exception as e:

        print(
            f"    [API ERROR] {e}"
        )

        return [], False

    if not data:

        print(
            "    API returned no data "
            "(window will be retried)"
        )

        return [], False

    departures = (
        data.get("departures")
        or []
    )

    arrivals = (
        data.get("arrivals")
        or []
    )

    print(
        f"    API returned "
        f"{len(departures)} departures + "
        f"{len(arrivals)} arrivals = "
        f"{len(departures) + len(arrivals)} records"
    )

    records = []

    # known_iata is the REAL IATA code for this monitored
    # airport (resolved from the airport table). AIRPORT_CODES
    # itself holds ICAO codes, and AeroDataBox sometimes omits
    # the airport's own IATA code on departure/arrival records
    # for the monitored airport, so we backfill with known_iata
    # instead of the ICAO code — writing the ICAO code into an
    # *_iata column would corrupt joins against airport.iata_code.
    # Fall back to the ICAO code only if we don't have an IATA
    # mapping yet (e.g. airport details haven't been fetched).
    backfill_code = known_iata or airport

    for flight in departures:

        record = parse_flight(
            flight,
            known_airport_iata=backfill_code,
            list_type="departures",
        )

        if record:
            records.append(record)

    for flight in arrivals:

        record = parse_flight(
            flight,
            known_airport_iata=backfill_code,
            list_type="arrivals",
        )

        if record:
            records.append(record)

    return records, True


# ================================================================
# STORE FLIGHTS
# ================================================================

def store_flights(
    conn,
    records,
):

    stored = 0

    for record in records:

        try:

            db.upsert_flight(
                conn,
                record,
            )

            stored += 1

        except Exception as e:

            print(
                "[DB ERROR] "
                f"{record.get('flight_id')} "
                f"-> {e}"
            )

    return stored


# ================================================================
# PROCESS ONE AIRPORT
# ================================================================

def process_airport(
    conn,
    airport,
    start_date,
    end_date,
    known_iata=None,
):

    print(
        f"\nPROCESSING AIRPORT: {airport}"
    )

    current = start_date

    total_stored = 0

    while current < end_date:

        window_end = (
            current + timedelta(hours=12)
        )

        if window_end > end_date:
            window_end = end_date

        from_local = (
            current.strftime(
                "%Y-%m-%dT%H:%M"
            )
        )

        to_local = (
            window_end.strftime(
                "%Y-%m-%dT%H:%M"
            )
        )

        records, success = (
            fetch_airport_window(
                conn,
                airport,
                from_local,
                to_local,
                known_iata=known_iata,
            )
        )

        if success:

            stored = store_flights(
                conn,
                records,
            )

            total_stored += stored

            db.mark_window_fetched(
                conn,
                airport,
                from_local,
                to_local,
            )

            conn.commit()

            print(
                f"    Stored/updated: "
                f"{stored} flights"
            )

        else:

            print(
                "    Window failed. "
                "It will be retried later."
            )

        current = window_end

    return total_stored


# ================================================================
# AIRPORT DETAILS
# ================================================================

def fetch_and_store_airports(
    conn,
):

    print()
    print(
        "-----------------------------------------------------------------"
    )
    print(
        "FETCHING AIRPORT DETAILS"
    )
    print(
        "-----------------------------------------------------------------"
    )

    if not FETCH_AIRPORT_DETAILS:

        print(
            "[INFO] FETCH_AIRPORT_DETAILS=0"
        )

        print(
            "       Creating/keeping airport "
            "stub rows only."
        )

        for code in AIRPORT_CODES:

            try:

                db.ensure_airport_stub(
                    conn,
                    code,
                )

            except Exception as e:

                print(
                    f"  [DB ERROR] "
                    f"{code}: {e}"
                )

        conn.commit()

        return

    for code in AIRPORT_CODES:

        if db.has_full_airport_by_icao(
            conn,
            code,
        ):

            print(
                f"  = {code}: "
                f"already have full details"
            )

            continue

        try:

            raw = (
                api_client.get_airport_info(
                    code
                )
            )

        except APIRateLimitError:

            print(
                "[STOP] API quota reached "
                "while fetching airport details."
            )

            raise

        except Exception as e:

            print(
                f"  ! {code}: "
                f"API error -> {e}"
            )

            db.ensure_airport_stub(
                conn,
                code,
            )

            conn.commit()

            continue

        parsed = parse_airport(
            raw,
            code,
        )

        if parsed:

            try:

                db.upsert_airport(
                    conn,
                    parsed,
                )

                conn.commit()

                print(
                    f"  + {code}: "
                    f"{parsed.get('name')} "
                    f"({parsed.get('iata_code')}) - "
                    f"{parsed.get('country')}"
                )

            except Exception as e:

                print(
                    f"  [DB ERROR] "
                    f"{code}: {e}"
                )

                conn.rollback()

        else:

            db.ensure_airport_stub(
                conn,
                code,
            )

            conn.commit()

            print(
                f"  ! {code}: "
                f"details unavailable; "
                f"kept as stub"
            )


# ================================================================
# AIRCRAFT DETAILS
# ================================================================

def fetch_and_store_stub_airport_details(
    conn,
):
    """
    Backfill details (country, in particular) for airports that
    are still stub rows.

    fetch_and_store_airports() only calls the AeroDataBox
    airport-details endpoint for the monitored AIRPORT_CODES list.
    Any airport that only ever appears as a flight origin/
    destination — e.g. LAS as the destination of a KLAX flight —
    is created by ensure_airport_stub() with just an iata_code and
    a placeholder name; country stays NULL.

    Query 5 in analysis_queries.sql labels a flight 'Unknown'
    whenever either endpoint's country isn't known yet (rather than
    guessing), so those flights stay 'Unknown' until this backfill
    runs. Each run resolves up to STUB_AIRPORT_FETCH_BATCH_SIZE of
    the most-referenced unresolved airports, ordered by how many
    flights use them, so the label converges to 'Domestic'/
    'International' over a few runs without one run using the
    whole API quota.
    """

    print()
    print(
        "-----------------------------------------------------------------"
    )
    print(
        "STUB AIRPORT BACKFILL (country/city/timezone)"
    )
    print(
        "-----------------------------------------------------------------"
    )

    codes = db.get_stub_airport_codes(
        conn,
        STUB_AIRPORT_FETCH_BATCH_SIZE,
    )

    if not codes:

        print(
            "[INFO] No stub airports left to backfill."
        )

        return

    print(
        f"Backfilling {len(codes)} "
        f"stub airport(s)..."
    )

    resolved = 0
    failed = 0

    for iata_code in codes:

        try:

            raw = (
                api_client.get_airport_info_by_iata(
                    iata_code
                )
            )

        except APIRateLimitError:

            print(
                "[STOP] API quota reached "
                "while backfilling stub airports."
            )

            raise

        except Exception as e:

            print(
                f"  ! {iata_code}: "
                f"API error -> {e}"
            )

            failed += 1

            continue

        parsed = parse_airport(
            raw,
            iata_code,
        )

        if not parsed or not parsed.get("country"):

            print(
                f"  ! {iata_code}: "
                f"country still unavailable"
            )

            # NOTE (bugfix): stamp the attempt even on failure.
            # Without this, get_stub_airport_codes() has no way to
            # know this code was already tried, so it re-selects
            # this same code (and every other unresolvable one
            # ranked above it) on every future run, permanently
            # starving the rest of the 886 stub airports of a
            # chance to be attempted at all.
            try:

                db.mark_airport_lookup(
                    conn,
                    iata_code,
                )

                conn.commit()

            except Exception:

                conn.rollback()

            failed += 1

            continue

        try:

            db.upsert_airport(
                conn,
                parsed,
            )

            conn.commit()

            print(
                f"  + {iata_code}: "
                f"{parsed.get('name')} - "
                f"{parsed.get('country')}"
            )

            resolved += 1

        except Exception as e:

            print(
                f"  [DB ERROR] "
                f"{iata_code}: {e}"
            )

            conn.rollback()

            failed += 1

    print(
        f"\nStub airports resolved: "
        f"{resolved}, "
        f"failed/still unknown: {failed}"
    )


def fetch_and_store_aircraft(
    conn,
):

    print()
    print(
        "-----------------------------------------------------------------"
    )
    print(
        "AIRCRAFT DETAILS"
    )
    print(
        "-----------------------------------------------------------------"
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT aircraft_registration
        FROM flights
        WHERE aircraft_registration IS NOT NULL
        ORDER BY aircraft_registration
        """
    )

    registrations = [
        row[0]
        for row in cursor.fetchall()
    ]

    cursor.close()

    print(
        f"  {len(registrations)} distinct aircraft "
        f"registrations found."
    )

    if not FETCH_AIRCRAFT_DETAILS:

        print(
            "[INFO] FETCH_AIRCRAFT_DETAILS=0."
        )

        print(
            "       Aircraft API calls are DISABLED."
        )

        print(
            "       Existing registrations remain "
            "available in flights."
        )

        return

    fetched = 0
    skipped = 0
    failed = 0

    cursor = conn.cursor()

    # NOTE (bugfix):
    # This query used to rank ALL registrations by flight_count and
    # take the top 20, with no way to ever reach registration #21+.
    # Since has_full_aircraft() causes already-fetched registrations
    # to be skipped, re-running extract_data.py kept re-selecting the
    # exact same top-20 registrations forever - every other aircraft
    # in the fleet stayed unfetched permanently, no matter how many
    # times the script was run.
    #
    # Fixing this by excluding registrations that already have a
    # model in the aircraft table, so each run advances to the next
    # batch instead of repeating the same one. Batch size is
    # AIRCRAFT_FETCH_BATCH_SIZE (config.py) rather than a hardcoded
    # 20, since 20/run is far too small relative to the number of
    # registrations with >=5 flights across 12 monitored airports.
    # NOTE (bugfix): previously this excluded a registration only
    # once it had a model, so a registration that failed lookup
    # (model still NULL, but last_aircraft_lookup now stamped by the
    # fix above) kept being re-selected every run. We now also
    # exclude "already attempted and confirmed unavailable"
    # registrations, while still retrying anything that was never
    # looked up at all (ac.registration IS NULL, or a stub row with
    # last_aircraft_lookup still NULL from before this fix).
    cursor.execute(
        f"""
        SELECT
            f.aircraft_registration,
            COUNT(*) AS flight_count
        FROM flights f
        LEFT JOIN aircraft ac
            ON ac.registration = f.aircraft_registration
        WHERE f.aircraft_registration IS NOT NULL
          AND (
                ac.registration IS NULL
                OR (ac.model IS NULL AND ac.last_aircraft_lookup IS NULL)
              )
        GROUP BY f.aircraft_registration
        ORDER BY flight_count DESC
        LIMIT {int(AIRCRAFT_FETCH_BATCH_SIZE)}
        """
    )

    priority_registrations = [
        row[0]
        for row in cursor.fetchall()
    ]

    cursor.close()

    print(
        f"  Priority aircraft selected: "
        f"{len(priority_registrations)}"
    )

    for registration in priority_registrations:

        if db.has_full_aircraft(
            conn,
            registration,
        ):

            skipped += 1

            print(
                f"  = {registration}: "
                f"already have details"
            )

            continue

        try:

            raw, rate_limited = (
                api_client.get_aircraft_info_safe(
                    registration
                )
            )

        except APIRateLimitError:

            print(
                "[STOP] Aircraft API quota reached."
            )

            break

        except Exception as e:

            print(
                f"  ! {registration}: {e}"
            )

            failed += 1

            continue

        if rate_limited:

            print(
                "[STOP] Aircraft API rate limit reached."
            )

            break

        parsed = parse_aircraft(
            raw,
            registration,
        )

        if parsed:

            try:

                db.upsert_aircraft(
                    conn,
                    parsed,
                )

                conn.commit()

                fetched += 1

                print(
                    f"  + {registration}: "
                    f"{parsed.get('model')}"
                )

            except Exception as e:

                print(
                    f"  [DB ERROR] "
                    f"{registration}: {e}"
                )

                conn.rollback()

                failed += 1

        else:

            try:

                db.ensure_aircraft_stub(
                    conn,
                    registration,
                )

                # NOTE (bugfix): without this, a registration that
                # AeroDataBox genuinely has no record for (raw not a
                # dict -> parsed is None) gets re-selected by the
                # priority query on every future run, forever - it
                # never has a model, so it never satisfies
                # has_full_aircraft(), and it re-consumes one of the
                # AIRCRAFT_FETCH_BATCH_SIZE API calls each time.
                # Stamping last_aircraft_lookup lets the priority
                # query (below) exclude it after one confirmed-failed
                # attempt, so quota goes to registrations that can
                # actually still be resolved.
                db.mark_aircraft_lookup(
                    conn,
                    registration,
                )

                conn.commit()

            except Exception:

                conn.rollback()

            failed += 1

    print(
        f"  Aircraft fetched: {fetched} | "
        f"already complete: {skipped} | "
        f"failed/stub: {failed}"
    )


# ================================================================
# ICAO -> IATA MAP (BULK)
# ================================================================

def build_icao_to_iata_map(
    conn,
    icao_codes,
):
    """
    Resolve every monitored ICAO code to its real IATA code in
    one query, for use as flight-record backfill values.

    Airports whose full details haven't been fetched yet (still
    a stub row) simply won't appear in the returned dict — callers
    should fall back to the ICAO code in that case.
    """

    if not icao_codes:
        return {}

    cursor = conn.cursor()

    placeholders = ", ".join(
        ["%s"] * len(icao_codes)
    )

    cursor.execute(
        f"""
        SELECT icao_code, iata_code
        FROM airport
        WHERE icao_code IN ({placeholders})
          AND iata_code IS NOT NULL
          AND iata_code <> icao_code
        """,
        tuple(icao_codes),
    )

    mapping = {
        row[0]: row[1]
        for row in cursor.fetchall()
    }

    cursor.close()

    return mapping


# ================================================================
# ICAO -> IATA LOOKUP
# ================================================================

def get_iata_for_icao(
    conn,
    icao_code,
):
    """
    Convert ICAO airport code to IATA code.

    Example:

        KATL -> ATL
        EGLL -> LHR
        KLAX -> LAX
    """

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT iata_code
        FROM airport
        WHERE icao_code = %s
        LIMIT 1
        """,
        (
            icao_code,
        ),
    )

    row = cursor.fetchone()

    cursor.close()

    if row:
        return row[0]

    return None


# ================================================================
# DELAY STATISTICS
# ================================================================

def fetch_and_store_delays(
    conn,
):
    """
    Fetch and store airport delay statistics.

    IMPORTANT:

    AIRPORT_CODES contains ICAO codes.

    AeroDataBox receives the ICAO code.

    The database receives the IATA code.

    Delay status is now tracked separately as:

        ALREADY EXISTS
        LIVE API
        API UNAVAILABLE
        CALCULATED
    """

    print()
    print(
        "-----------------------------------------------------------------"
    )
    print(
        "FETCHING AIRPORT DELAY STATISTICS"
    )
    print(
        "-----------------------------------------------------------------"
    )

    from fetch_delays import (
        compute_counts,
        compute_delay_minutes,
    )

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    already_existing = 0
    api_live = 0
    api_unavailable = 0
    calculated_rows = 0
    failed = 0

    for icao_code in AIRPORT_CODES:

        # --------------------------------------------------------
        # ICAO -> IATA
        # --------------------------------------------------------

        iata_code = get_iata_for_icao(
            conn,
            icao_code,
        )

        if not iata_code:

            print(
                f"  [DB ERROR] "
                f"{icao_code}: "
                f"Could not find IATA code."
            )

            failed += 1

            continue

        # --------------------------------------------------------
        # CHECK EXISTING ROW
        # --------------------------------------------------------

        if db.has_delay_for_date(
            conn,
            iata_code,
            today,
        ):

            already_existing += 1

            print(
                f"  = {icao_code} "
                f"({iata_code}): "
                f"ALREADY EXISTS for {today} "
                f"(API not called)"
            )

            continue

        # --------------------------------------------------------
        # API CALL
        # --------------------------------------------------------

        try:

            raw = (
                api_client.get_airport_delays(
                    icao_code
                )
            )

        except APIRateLimitError:

            print()
            print(
                "[STOP] API quota reached "
                "while fetching delay statistics."
            )

            print(
                "Already collected delay data is safe."
            )

            break

        except Exception as e:

            error_text = str(e)

            # ----------------------------------------------------
            # Detect known unavailable endpoint condition.
            # ----------------------------------------------------

            if (
                "400" in error_text
                or "unavailable" in error_text.lower()
                or "obsolete" in error_text.lower()
            ):

                api_unavailable += 1

                print(
                    f"  ! {icao_code} "
                    f"({iata_code}): "
                    f"API UNAVAILABLE"
                )

            else:

                failed += 1

                print(
                    f"  ! {icao_code} "
                    f"({iata_code}): "
                    f"delay API failed -> {e}"
                )

            # ----------------------------------------------------
            # IMPORTANT:
            #
            # Even if live /delays is unavailable, we can still
            # calculate delay statistics from our own flights.
            # ----------------------------------------------------

            raw = None

        # --------------------------------------------------------
        # API STATUS
        # --------------------------------------------------------

        if raw:

            api_live += 1

            print(
                f"  [API] {icao_code} "
                f"({iata_code}): "
                f"LIVE delay data available"
            )

        # --------------------------------------------------------
        # CALCULATE FROM OUR FLIGHTS TABLE
        # --------------------------------------------------------

        try:

            parsed = compute_counts(
                conn,
                iata_code,
            )

        except Exception as e:

            print(
                f"  [DB ERROR] "
                f"{icao_code} ({iata_code}): "
                f"could not calculate counts -> {e}"
            )

            failed += 1

            continue

        # --------------------------------------------------------
        # DELAY MINUTES
        # --------------------------------------------------------

        try:

            (
                avg_delay_min,
                median_delay_min,
            ) = compute_delay_minutes(
                conn,
                iata_code,
            )

            parsed[
                "avg_delay_min"
            ] = avg_delay_min

            parsed[
                "median_delay_min"
            ] = median_delay_min

        except Exception as e:

            print(
                f"  ! {icao_code} "
                f"({iata_code}): "
                f"could not calculate delay minutes "
                f"-> {e}"
            )

            parsed[
                "avg_delay_min"
            ] = None

            parsed[
                "median_delay_min"
            ] = None

        # --------------------------------------------------------
        # FORCE IATA
        # --------------------------------------------------------

        parsed[
            "airport_iata"
        ] = iata_code

        parsed[
            "delay_date"
        ] = today

        # --------------------------------------------------------
        # STORE
        # --------------------------------------------------------

        try:

            db.upsert_delay(
                conn,
                parsed,
            )

            conn.commit()

            calculated_rows += 1

            avg_display = (
                parsed[
                    "avg_delay_min"
                ]
                if parsed[
                    "avg_delay_min"
                ] is not None
                else "N/A"
            )

            median_display = (
                parsed[
                    "median_delay_min"
                ]
                if parsed[
                    "median_delay_min"
                ] is not None
                else "N/A"
            )

            print(
                f"  SUCCESS: "
                f"{icao_code} ({iata_code}) | "
                f"total={parsed['total_flights']} | "
                f"delayed={parsed['delayed_flights']} | "
                f"cancelled={parsed['canceled_flights']} | "
                f"avg_delay={avg_display}min | "
                f"median_delay={median_display}min"
            )

        except Exception as e:

            print(
                f"  [DB ERROR] "
                f"{icao_code} ({iata_code}): "
                f"{e}"
            )

            conn.rollback()

            failed += 1

    # ============================================================
    # FINAL DELAY SUMMARY
    # ============================================================

    print()
    print(
        "-----------------------------------------------------------------"
    )
    print(
        "DELAY STATISTICS SUMMARY"
    )
    print(
        "-----------------------------------------------------------------"
    )

    print(
        f"  Already existed : "
        f"{already_existing}"
    )

    print(
        f"  Live API data   : "
        f"{api_live}"
    )

    print(
        f"  API unavailable : "
        f"{api_unavailable}"
    )

    print(
        f"  Newly calculated : "
        f"{calculated_rows}"
    )

    print(
        f"  Failed          : "
        f"{failed}"
    )

    print()

    print(
        f"  Total airports processed: "
        f"{len(AIRPORT_CODES)}"
    )

    print(
        "-----------------------------------------------------------------"
    )


# ================================================================
# MAIN
# ================================================================

def main():

    print()
    print(
        "================================================================="
    )
    print(
        "AIR TRACKER ETL - STARTING"
    )
    print(
        "================================================================="
    )

    print(
        f"Airports configured : "
        f"{len(AIRPORT_CODES)}"
    )

    print(
        f"Days to fetch       : "
        f"{DAYS_BACK}"
    )

    print(
        f"Skip flights        : "
        f"{SKIP_FLIGHTS}"
    )

    print(
        f"Airport API         : "
        f"{FETCH_AIRPORT_DETAILS}"
    )

    print(
        f"Aircraft API        : "
        f"{FETCH_AIRCRAFT_DETAILS}"
    )

    # ============================================================
    # DATABASE
    # ============================================================

    db.init_db()

    conn = db.get_connection()

    if not conn:

        print(
            "[FATAL] Could not connect to MySQL."
        )

        return

    try:

        # ========================================================
        # STEP 1 — AIRPORT DETAILS
        # ========================================================

        print()
        print(
            "STEP 1/4: AIRPORT DETAILS"
        )

        fetch_and_store_airports(
            conn
        )

        # ========================================================
        # STEP 2 — FLIGHT DATA
        # ========================================================

        print()
        print(
            "STEP 2/4: FLIGHT DATA"
        )

        if SKIP_FLIGHTS:

            print(
                "[INFO] SKIP_FLIGHTS=1."
            )

            print(
                "       Existing flight data "
                "will not be touched."
            )

        else:

            end_date = (
                datetime.now()
                .replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            )

            start_date = (
                end_date
                - timedelta(
                    days=DAYS_BACK
                )
            )

            print(
                f"Date range: "
                f"{start_date.strftime('%Y-%m-%d')} "
                f"-> "
                f"{end_date.strftime('%Y-%m-%d')}"
            )

            total_processed = 0

            # Resolve ICAO -> real IATA up front so that any
            # backfilled origin/destination airport code on a
            # flight record is a genuine IATA code, not the ICAO
            # code used to talk to AeroDataBox.
            icao_to_iata = build_icao_to_iata_map(
                conn,
                AIRPORT_CODES,
            )

            try:

                for airport in AIRPORT_CODES:

                    processed = (
                        process_airport(
                            conn,
                            airport,
                            start_date,
                            end_date,
                            known_iata=icao_to_iata.get(
                                airport
                            ),
                        )
                    )

                    total_processed += (
                        processed
                    )

            except APIRateLimitError:

                print()
                print(
                    "================================================================="
                )
                print(
                    "API QUOTA REACHED"
                )
                print(
                    "================================================================="
                )

                print(
                    "Stopping extraction safely."
                )

                print(
                    "Already processed windows "
                    "are saved."
                )

                print(
                    "The current unfinished window "
                    "was NOT marked as fetched."
                )

                print(
                    "Run the script again later "
                    "to resume."
                )

                print(
                    "================================================================="
                )

            print(
                f"\nTotal flights stored/updated: "
                f"{total_processed}"
            )

        # ========================================================
        # STEP 3 — STUB AIRPORT BACKFILL
        # ========================================================

        print()
        print(
            "STEP 3/5: STUB AIRPORT BACKFILL"
        )

        if not FETCH_AIRPORT_DETAILS:

            print(
                "[INFO] FETCH_AIRPORT_DETAILS=0. "
                "Skipping stub airport backfill "
                "(query 5 will keep showing 'Unknown')."
            )

        else:

            try:

                fetch_and_store_stub_airport_details(
                    conn
                )

            except APIRateLimitError:

                print(
                    "[INFO] Airport API quota reached."
                )

                print(
                    "Skipping remaining stub airport calls."
                )

        # ========================================================
        # STEP 4 — AIRCRAFT DETAILS
        # ========================================================

        print()
        print(
            "STEP 4/5: AIRCRAFT DETAILS"
        )

        try:

            fetch_and_store_aircraft(
                conn
            )

        except APIRateLimitError:

            print(
                "[INFO] Aircraft API quota reached."
            )

            print(
                "Skipping remaining aircraft calls."
            )

        # ========================================================
        # STEP 5 — DELAY STATISTICS
        # ========================================================

        print()
        print(
            "STEP 5/5: DELAY STATISTICS"
        )

        try:

            fetch_and_store_delays(
                conn
            )

        except APIRateLimitError:

            print(
                "[INFO] Delay API quota reached."
            )

            print(
                "Skipping remaining delay calls."
            )

    except KeyboardInterrupt:

        print()
        print(
            "[STOPPED] ETL interrupted by user."
        )

        print(
            "Committed data is safe."
        )

    except Exception as e:

        print()
        print(
            "[FATAL ETL ERROR]"
        )

        print(
            str(e)
        )

    finally:

        try:
            conn.commit()
        except Exception:
            pass

        try:
            conn.close()
        except Exception:
            pass

    print()
    print(
        "================================================================="
    )
    print(
        "AIR TRACKER ETL - COMPLETE"
    )
    print(
        "================================================================="
    )

    print(
        "Next:"
    )

    print(
        "  python run_queries.py"
    )

    print(
        "  streamlit run app.py"
    )


# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":

    if "--debug-aircraft" in sys.argv:

        idx = sys.argv.index("--debug-aircraft")

        reg_arg = (
            sys.argv[idx + 1]
            if len(sys.argv) > idx + 1
            else None
        )

        debug_aircraft_api(
            reg_arg
        )

    elif "--debug-flight-times" in sys.argv:

        idx = sys.argv.index("--debug-flight-times")

        icao_arg = (
            sys.argv[idx + 1]
            if len(sys.argv) > idx + 1
            else None
        )

        debug_flight_times(
            icao_arg
        )

    else:

        main()