"""
Air Tracker - MySQL Database Manager

Responsibilities:
- Create/initialize the Air Tracker database
- Manage MySQL connections
- Insert/update airports
- Insert/update aircraft
- Insert/update flights
- Insert/update airport delay statistics
- Track successfully fetched flight windows
- Preserve existing data
- Provide safe helper functions for ETL

Install:
    pip install mysql-connector-python
"""

import mysql.connector
from mysql.connector import Error

from config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
)


# ================================================================
# CONNECTIONS
# ================================================================

def _server_connection():
    """
    Connect to MySQL server without selecting a database.
    Used when creating the Air Tracker database.
    """

    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def get_connection():
    """
    Connect directly to the Air Tracker database.
    """

    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


# ================================================================
# DATABASE INITIALIZATION
# ================================================================

def init_db(
    schema_path: str = "schema.sql",
    force_recreate: bool = False,
):
    """
    Create the database and required tables.

    Existing data is preserved by default.

    force_recreate=False:
        Keep existing database/tables/data.

    force_recreate=True:
        Execute schema.sql again.

    IMPORTANT:
        schema.sql itself should NOT contain DROP TABLE statements
        unless you intentionally want to destroy existing data.
    """

    server_conn = None
    conn = None
    cursor = None

    try:

        # --------------------------------------------------------
        # Create database if necessary
        # --------------------------------------------------------

        server_conn = _server_connection()
        cursor = server_conn.cursor()

        # DB_NAME comes from trusted local configuration.
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`"
        )

        server_conn.commit()

        cursor.close()
        cursor = None

        server_conn.close()
        server_conn = None

        # --------------------------------------------------------
        # Connect to actual database
        # --------------------------------------------------------

        conn = get_connection()
        cursor = conn.cursor()

        # --------------------------------------------------------
        # Existing database check
        # --------------------------------------------------------

        if not force_recreate:

            cursor.execute(
                "SHOW TABLES LIKE 'flights'"
            )

            if cursor.fetchone():

                print(
                    f"MySQL database '{DB_NAME}' already exists."
                )

                print(
                    "Keeping existing data."
                )

                # ------------------------------------------------
                # Upgrade older installations
                # ------------------------------------------------

                _ensure_fetched_windows_table(
                    conn
                )

                _ensure_airport_columns(
                    conn
                )

                _ensure_aircraft_columns(
                    conn
                )

                _ensure_delay_columns(
                    conn
                )

                conn.commit()

                return

        # --------------------------------------------------------
        # Fresh schema creation
        # --------------------------------------------------------

        with open(
            schema_path,
            "r",
            encoding="utf-8",
        ) as f:

            sql_script = f.read()

        # Remove empty statements safely.
        statements = [
            statement.strip()
            for statement in sql_script.split(";")
            if statement.strip()
        ]

        for statement in statements:

            cursor.execute(
                statement
            )

        conn.commit()

        # Ensure ETL tracking table exists even if an older
        # schema.sql was supplied.
        _ensure_fetched_windows_table(
            conn
        )

        conn.commit()

        print(
            f"MySQL database '{DB_NAME}' "
            f"initialized successfully."
        )

    except Error as e:

        if conn:

            try:
                conn.rollback()
            except Exception:
                pass

        print(
            f"[DATABASE ERROR] {e}"
        )

        raise

    finally:

        if cursor:

            try:
                cursor.close()
            except Exception:
                pass

        if conn:

            try:
                conn.close()
            except Exception:
                pass

        if server_conn:

            try:
                server_conn.close()
            except Exception:
                pass


# ================================================================
# DATABASE UPGRADE HELPERS
# ================================================================

def _ensure_fetched_windows_table(
    conn,
):
    """
    Ensure fetched_windows exists.

    This is important for databases created using an older
    schema.sql.
    """

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fetched_windows (

            id INT AUTO_INCREMENT PRIMARY KEY,

            airport_iata VARCHAR(10) NOT NULL,

            window_start VARCHAR(20) NOT NULL,

            window_end VARCHAR(20) NOT NULL,

            UNIQUE KEY uniq_window (
                airport_iata,
                window_start,
                window_end
            )

        )
        """
    )

    cursor.close()


def _ensure_airport_columns(
    conn,
):
    """
    Upgrade helper.

    Does not modify existing values.
    """

    cursor = conn.cursor()

    cursor.execute(
        "SHOW COLUMNS FROM airport"
    )

    columns = {
        row[0]
        for row in cursor.fetchall()
    }

    if "icao_code" not in columns:

        cursor.execute(
            """
            ALTER TABLE airport
            ADD COLUMN icao_code VARCHAR(10)
            AFTER airport_id
            """
        )

    if "iata_code" not in columns:

        cursor.execute(
            """
            ALTER TABLE airport
            ADD COLUMN iata_code VARCHAR(10)
            """
        )

    if "last_airport_lookup" not in columns:

        # Same fix as aircraft.last_aircraft_lookup: without a
        # timestamp marking "we already tried this one and it
        # didn't resolve", get_stub_airport_codes() has no way to
        # tell a never-attempted stub apart from a
        # confirmed-unresolvable one, so it re-selects the exact
        # same top-N-by-flight-count stub airports every run.
        cursor.execute(
            """
            ALTER TABLE airport
            ADD COLUMN last_airport_lookup DATETIME NULL
            """
        )

    cursor.close()


def _ensure_aircraft_columns(conn):
    """Upgrade the aircraft table without destroying existing data."""
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM aircraft")
    columns = {row[0] for row in cursor.fetchall()}

    if "icao_type_code" not in columns:
        cursor.execute(
            "ALTER TABLE aircraft ADD COLUMN icao_type_code VARCHAR(20)"
        )

    if "owner" not in columns:
        cursor.execute(
            "ALTER TABLE aircraft ADD COLUMN owner VARCHAR(255)"
        )

    if "last_aircraft_lookup" not in columns:
        cursor.execute(
            "ALTER TABLE aircraft ADD COLUMN "
            "last_aircraft_lookup DATETIME NULL"
        )

    cursor.close()
def _ensure_delay_columns(
    conn,
):
    """
    Upgrade helper for airport_delays.

    The current ETL stores average and median delay minutes.
    """

    cursor = conn.cursor()

    cursor.execute(
        "SHOW COLUMNS FROM airport_delays"
    )

    columns = {
        row[0]
        for row in cursor.fetchall()
    }

    if "avg_delay_min" not in columns:

        cursor.execute(
            """
            ALTER TABLE airport_delays
            ADD COLUMN avg_delay_min DECIMAL(10,2)
            """
        )

    if "median_delay_min" not in columns:

        cursor.execute(
            """
            ALTER TABLE airport_delays
            ADD COLUMN median_delay_min DECIMAL(10,2)
            """
        )

    cursor.close()


# ================================================================
# AIRPORT STUB
# ================================================================

def ensure_airport_stub(
    conn,
    iata_code: str,
):
    """
    Ensure an airport exists so flights can satisfy
    the airport foreign-key relationship.

    Only the IATA code and name are populated.

    Full airport information can later replace the stub.
    """

    if not iata_code:

        return

    iata_code = str(
        iata_code
    ).strip().upper()

    if not iata_code:

        return

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT IGNORE INTO airport (
            iata_code,
            name
        )
        VALUES (
            %s,
            %s
        )
        """,
        (
            iata_code,
            iata_code,
        ),
    )

    cursor.close()


def mark_airport_lookup(
    conn,
    iata_code: str,
):
    """
    Record an attempted stub-airport API lookup, including failed
    ones (unknown code, no country in the response, etc.).

    Without this, get_stub_airport_codes() can't distinguish a
    never-attempted stub from one that was already tried and
    couldn't be resolved, so it keeps re-selecting the same
    top-N-by-flight-count stub codes forever and never reaches the
    rest - see the fix applied to aircraft lookups
    (mark_aircraft_lookup) for the identical issue.
    """

    if not iata_code:

        return

    iata_code = str(
        iata_code
    ).strip().upper()

    ensure_airport_stub(
        conn,
        iata_code,
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE airport
        SET last_airport_lookup = NOW()
        WHERE iata_code = %s
        """,
        (iata_code,),
    )

    cursor.close()


# ================================================================
# AIRCRAFT STUB
# ================================================================

def ensure_aircraft_stub(
    conn,
    registration: str,
):
    """
    Ensure an aircraft registration exists.

    This prevents flight inserts from failing when aircraft
    details have not yet been fetched.
    """

    if not registration:

        return

    registration = str(
        registration
    ).strip().upper()

    if not registration:

        return

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT IGNORE INTO aircraft (
            registration
        )
        VALUES (
            %s
        )
        """,
        (
            registration,
        ),
    )

    cursor.close()


# ================================================================
# AIRPORT UPSERT
# ================================================================

def upsert_airport(
    conn,
    a: dict,
):
    """
    Insert or update airport details.

    NULL values from a newer API response do NOT overwrite
    existing useful values.
    """

    if not a:

        return

    iata_code = (
        a.get("iata_code")
    )

    if not iata_code:

        return

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO airport (

            icao_code,
            iata_code,
            name,
            city,
            country,
            continent,
            latitude,
            longitude,
            timezone,
            last_airport_lookup

        )
        VALUES (

            %(icao_code)s,
            %(iata_code)s,
            %(name)s,
            %(city)s,
            %(country)s,
            %(continent)s,
            %(latitude)s,
            %(longitude)s,
            %(timezone)s,
            NOW()

        )

        ON DUPLICATE KEY UPDATE

            last_airport_lookup = NOW(),

            icao_code = COALESCE(
                VALUES(icao_code),
                icao_code
            ),

            name = COALESCE(
                VALUES(name),
                name
            ),

            city = COALESCE(
                VALUES(city),
                city
            ),

            country = COALESCE(
                VALUES(country),
                country
            ),

            continent = COALESCE(
                VALUES(continent),
                continent
            ),

            latitude = COALESCE(
                VALUES(latitude),
                latitude
            ),

            longitude = COALESCE(
                VALUES(longitude),
                longitude
            ),

            timezone = COALESCE(
                VALUES(timezone),
                timezone
            )
        """,
        a,
    )

    cursor.close()


# ================================================================
# AIRCRAFT UPSERT
# ================================================================

def upsert_aircraft(conn, a: dict):
    """Insert/update aircraft details while preserving good existing values."""
    if not a or not a.get("registration"):
        return

    registration = str(a["registration"]).strip().upper()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO aircraft
            (registration, model, manufacturer, icao_type_code, owner,
             last_aircraft_lookup)
        VALUES
            (%(registration)s, %(model)s, %(manufacturer)s,
             %(icao_type_code)s, %(owner)s, NOW())
        ON DUPLICATE KEY UPDATE
            model = COALESCE(NULLIF(VALUES(model), ''), model),
            manufacturer = COALESCE(NULLIF(VALUES(manufacturer), ''), manufacturer),
            icao_type_code = COALESCE(NULLIF(VALUES(icao_type_code), ''), icao_type_code),
            owner = COALESCE(NULLIF(VALUES(owner), ''), owner),
            last_aircraft_lookup = NOW()
        """,
        {
            "registration": registration,
            "model": a.get("model"),
            "manufacturer": a.get("manufacturer"),
            "icao_type_code": a.get("icao_type_code"),
            "owner": a.get("owner"),
        },
    )
    cursor.close()


def mark_aircraft_lookup(conn, registration):
    """Record an attempted aircraft API lookup, including failed lookups."""
    if not registration:
        return
    registration = str(registration).strip().upper()
    ensure_aircraft_stub(conn, registration)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE aircraft
        SET last_aircraft_lookup = NOW()
        WHERE registration = %s
        """,
        (registration,),
    )
    cursor.close()

# ================================================================
# FLIGHT UPSERT
# ================================================================

def _normalize_airport_fk(conn, value):
    """
    Normalize a flight airport value to the IATA value stored in airport.
    Four-character ICAO values are translated through airport.icao_code.
    Unknown/non-IATA values are rejected instead of creating bogus stubs.
    """
    if not value:
        return None
    value = str(value).strip().upper()
    if len(value) == 3:
        return value

    if len(value) == 4:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT iata_code
            FROM airport
            WHERE UPPER(icao_code) = %s
              AND iata_code IS NOT NULL
            LIMIT 1
            """,
            (value,),
        )
        row = cursor.fetchone()
        cursor.close()
        return row[0].strip().upper() if row and row[0] else None

    return None


def upsert_flight(conn, f: dict):
    """Insert/update a flight without allowing NULLs or ICAO codes to corrupt good data."""
    if not f or not f.get("flight_id"):
        return

    origin_iata = _normalize_airport_fk(conn, f.get("origin_iata"))
    destination_iata = _normalize_airport_fk(conn, f.get("destination_iata"))

    aircraft_registration = f.get("aircraft_registration")
    if aircraft_registration:
        aircraft_registration = str(aircraft_registration).strip().upper()
        ensure_aircraft_stub(conn, aircraft_registration)

    if origin_iata:
        ensure_airport_stub(conn, origin_iata)
    if destination_iata:
        ensure_airport_stub(conn, destination_iata)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO flights (
            flight_id, flight_number, aircraft_registration,
            origin_iata, destination_iata,
            scheduled_departure, actual_departure,
            scheduled_arrival, actual_arrival,
            status, airline_code
        )
        VALUES (
            %(flight_id)s, %(flight_number)s, %(aircraft_registration)s,
            %(origin_iata)s, %(destination_iata)s,
            %(scheduled_departure)s, %(actual_departure)s,
            %(scheduled_arrival)s, %(actual_arrival)s,
            %(status)s, %(airline_code)s
        )
        ON DUPLICATE KEY UPDATE
            flight_number = COALESCE(VALUES(flight_number), flight_number),
            aircraft_registration = COALESCE(VALUES(aircraft_registration), aircraft_registration),
            origin_iata = COALESCE(VALUES(origin_iata), origin_iata),
            destination_iata = COALESCE(VALUES(destination_iata), destination_iata),
            scheduled_departure = COALESCE(VALUES(scheduled_departure), scheduled_departure),
            actual_departure = COALESCE(VALUES(actual_departure), actual_departure),
            scheduled_arrival = COALESCE(VALUES(scheduled_arrival), scheduled_arrival),
            actual_arrival = COALESCE(VALUES(actual_arrival), actual_arrival),
            status = COALESCE(VALUES(status), status),
            airline_code = COALESCE(VALUES(airline_code), airline_code)
        """,
        {
            "flight_id": f["flight_id"],
            "flight_number": f.get("flight_number"),
            "aircraft_registration": aircraft_registration,
            "origin_iata": origin_iata,
            "destination_iata": destination_iata,
            "scheduled_departure": f.get("scheduled_departure"),
            "actual_departure": f.get("actual_departure"),
            "scheduled_arrival": f.get("scheduled_arrival"),
            "actual_arrival": f.get("actual_arrival"),
            "status": f.get("status"),
            "airline_code": f.get("airline_code"),
        },
    )
    cursor.close()

# ================================================================
# DELAY STATISTICS
# ================================================================

def upsert_delay(
    conn,
    d: dict,
):
    """
    Insert or update airport delay statistics.

    Expected dictionary:

        airport_iata
        delay_date
        total_flights
        delayed_flights
        avg_delay_min
        median_delay_min
        canceled_flights
    """

    if not d:

        return

    airport_iata = (
        d.get("airport_iata")
    )

    delay_date = (
        d.get("delay_date")
    )

    if not airport_iata or not delay_date:

        return

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO airport_delays (

            airport_iata,
            delay_date,
            total_flights,
            delayed_flights,
            avg_delay_min,
            median_delay_min,
            canceled_flights

        )
        VALUES (

            %(airport_iata)s,
            %(delay_date)s,
            %(total_flights)s,
            %(delayed_flights)s,
            %(avg_delay_min)s,
            %(median_delay_min)s,
            %(canceled_flights)s

        )

        ON DUPLICATE KEY UPDATE

            total_flights = VALUES(
                total_flights
            ),

            delayed_flights = VALUES(
                delayed_flights
            ),

            avg_delay_min = VALUES(
                avg_delay_min
            ),

            median_delay_min = VALUES(
                median_delay_min
            ),

            canceled_flights = VALUES(
                canceled_flights
            )
        """,
        d,
    )

    cursor.close()


# ================================================================
# AIRPORT CHECK
# ================================================================

def has_full_airport(
    conn,
    iata_code: str,
) -> bool:
    """
    Check whether the airport contains meaningful details,
    looked up by IATA code.
    """

    if not iata_code:

        return False

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM airport
        WHERE iata_code = %s
          AND icao_code IS NOT NULL
          AND name IS NOT NULL
        LIMIT 1
        """,
        (
            iata_code,
        ),
    )

    found = (
        cursor.fetchone()
        is not None
    )

    cursor.close()

    return found


def get_stub_airport_codes(
    conn,
    limit: int,
):
    """
    Return up to `limit` IATA codes for airports that are still
    stub rows (country not yet known) — i.e. airports that showed
    up as a flight origin/destination but were never one of the
    monitored AIRPORT_CODES, so fetch_and_store_airports() never
    fetched their details.

    Ordered by how many flights reference the airport (as either
    origin or destination) so the most-used unresolved airports
    get backfilled first when the batch size is smaller than the
    total number of stub rows.

    NOTE (bugfix): this used to only filter on `country IS NULL`,
    with nothing to distinguish a stub that was never looked up
    from one that WAS looked up but AeroDataBox has no/incomplete
    data for (e.g. small private fields, or a garbage code like
    'NaN' from a bad upstream value). Since the ORDER BY is
    deterministic, that meant every run re-selected the exact same
    top-`limit` codes by flight count - if any of those never
    resolve, they permanently block every code ranked below them
    from ever being attempted, no matter how many times
    extract_data.py is run. This mirrors the identical bug already
    fixed for aircraft (see mark_aircraft_lookup) - the fix here is
    the same: skip anything already stamped with
    last_airport_lookup, so each run advances to the next batch of
    codes actually worth trying.
    """

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT a.iata_code
        FROM airport a
        LEFT JOIN flights fo ON fo.origin_iata = a.iata_code
        LEFT JOIN flights fd ON fd.destination_iata = a.iata_code
        WHERE a.country IS NULL
          AND a.iata_code IS NOT NULL
          AND a.last_airport_lookup IS NULL
        GROUP BY a.iata_code
        ORDER BY COUNT(fo.flight_id) + COUNT(fd.flight_id) DESC
        LIMIT %s
        """,
        (
            limit,
        ),
    )

    rows = cursor.fetchall()

    cursor.close()

    return [
        row[0]
        for row in rows
    ]


def has_full_airport_by_icao(
    conn,
    icao_code: str,
) -> bool:
    """
    Check whether the airport contains meaningful details,
    looked up by ICAO code.

    AIRPORT_CODES in config.py holds ICAO codes, so extract_data.py
    must check "have we already fetched this airport" against
    icao_code, not iata_code — otherwise this check always misses
    and every run re-fetches all monitored airports' details.
    """

    if not icao_code:

        return False

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM airport
        WHERE icao_code = %s
          AND iata_code IS NOT NULL
          AND name IS NOT NULL
        LIMIT 1
        """,
        (
            icao_code,
        ),
    )

    found = (
        cursor.fetchone()
        is not None
    )

    cursor.close()

    return found


# ================================================================
# AIRCRAFT CHECK
# ================================================================

def has_full_aircraft(
    conn,
    registration: str,
) -> bool:
    """
    Check whether aircraft details have been populated.
    """

    if not registration:

        return False

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM aircraft
        WHERE registration = %s
          AND model IS NOT NULL
        LIMIT 1
        """,
        (
            registration,
        ),
    )

    found = (
        cursor.fetchone()
        is not None
    )

    cursor.close()

    return found


# ================================================================
# DELAY CHECK
# ================================================================

def has_delay_for_date(
    conn,
    airport_iata: str,
    delay_date: str,
) -> bool:
    """
    Check whether delay statistics already exist for
    an airport/date combination.
    """

    if not airport_iata or not delay_date:

        return False

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM airport_delays
        WHERE airport_iata = %s
          AND delay_date = %s
        LIMIT 1
        """,
        (
            airport_iata,
            delay_date,
        ),
    )

    found = (
        cursor.fetchone()
        is not None
    )

    cursor.close()

    return found


# ================================================================
# FETCHED WINDOWS
# ================================================================

def mark_window_fetched(
    conn,
    airport_iata: str,
    window_start: str,
    window_end: str,
):
    """
    Mark a flight API window as successfully fetched.

    IMPORTANT:
        This function should ONLY be called after the API request
        succeeded and the data has been processed.
    """

    if (
        not airport_iata
        or not window_start
        or not window_end
    ):

        return

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT IGNORE INTO fetched_windows (

            airport_iata,
            window_start,
            window_end

        )
        VALUES (

            %s,
            %s,
            %s

        )
        """,
        (
            airport_iata,
            window_start,
            window_end,
        ),
    )

    cursor.close()


def has_window_been_fetched(
    conn,
    airport_iata: str,
    window_start: str,
    window_end: str,
) -> bool:
    """
    Check whether a flight API window was successfully fetched.
    """

    if (
        not airport_iata
        or not window_start
        or not window_end
    ):

        return False

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM fetched_windows
        WHERE airport_iata = %s
          AND window_start = %s
          AND window_end = %s
        LIMIT 1
        """,
        (
            airport_iata,
            window_start,
            window_end,
        ),
    )

    found = (
        cursor.fetchone()
        is not None
    )

    cursor.close()

    return found