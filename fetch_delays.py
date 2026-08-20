"""
Fetch airport delay statistics for Air Tracker.

Uses ICAO codes for the AeroDataBox API request, but converts them
to IATA codes before reading/writing airport_delays because the
database uses airport.iata_code as the foreign-key reference.

Delay counts are calculated from our own flights table.
Average and median delay minutes are calculated from scheduled vs
actual departure/arrival times stored in flights.
"""

import time
from datetime import datetime

import api_client
import db_manager

from config import AIRPORT_CODES, DB_NAME


# ================================================================
# AIRPORT CODE CONVERSION
# ================================================================

def get_iata_code(conn, icao_code):
    """
    Convert an ICAO airport code to its IATA code using our
    airport table.

    Example:
        KATL -> ATL
        EGLL -> LHR
        VIDP -> DEL
    """

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT iata_code
        FROM airport
        WHERE icao_code = %s
        LIMIT 1
        """,
        (icao_code,),
    )

    row = cursor.fetchone()

    cursor.close()

    if row:
        return row[0]

    return None


# ================================================================
# DELAY MINUTES
# ================================================================

def compute_delay_minutes(conn, iata_code):
    """
    Calculate average and median delay minutes from the flights table.

    Uses both:
      - departures FROM the airport
      - arrivals INTO the airport

    Negative delays are treated as 0.

    Values above 720 minutes are discarded as implausible data.

    NOTE: this used to also discard values between 300-360 minutes
    as "possible timezone mismatches." That band was a symptom of
    extract_data.py preferring local time over UTC when extracting
    scheduled_departure/actual_departure/scheduled_arrival/
    actual_arrival - local times for the same field pair could come
    from different bases, producing a bogus ~5-6 hour "delay." Now
    that extraction consistently uses UTC for all four fields, that
    band-aid is no longer needed and has been removed - a genuine
    5-6 hour delay is now stored as exactly that, not silently
    dropped.

    At least 5 valid samples are required before reporting an
    average/median. Otherwise NULL is returned.
    """

    MAX_PLAUSIBLE_DELAY_MIN = 720
    MIN_DELAY_SAMPLES = 5

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT TIMESTAMPDIFF(
            MINUTE,
            scheduled_departure,
            actual_departure
        )
        FROM flights
        WHERE origin_iata = %s
          AND scheduled_departure IS NOT NULL
          AND actual_departure IS NOT NULL

        UNION ALL

        SELECT TIMESTAMPDIFF(
            MINUTE,
            scheduled_arrival,
            actual_arrival
        )
        FROM flights
        WHERE destination_iata = %s
          AND scheduled_arrival IS NOT NULL
          AND actual_arrival IS NOT NULL
        """,
        (
            iata_code,
            iata_code,
        ),
    )

    raw_diffs = [
        row[0]
        for row in cursor.fetchall()
        if row[0] is not None
    ]

    cursor.close()

    delays = []

    for diff in raw_diffs:

        if abs(diff) > MAX_PLAUSIBLE_DELAY_MIN:
            continue

        delays.append(max(0, diff))

    discarded_cap = sum(
        1
        for diff in raw_diffs
        if abs(diff) > MAX_PLAUSIBLE_DELAY_MIN
    )

    if discarded_cap:
        print(
            f"    [DELAY WARNING] {iata_code}: "
            f"discarded {discarded_cap} implausible delay value(s) "
            f"over {MAX_PLAUSIBLE_DELAY_MIN} minutes."
        )

    if len(delays) < MIN_DELAY_SAMPLES:

        if delays:
            print(
                f"    [DELAY WARNING] {iata_code}: "
                f"only {len(delays)} valid delay sample(s). "
                f"Need at least {MIN_DELAY_SAMPLES}. "
                f"Storing NULL."
            )

        return None, None

    delays.sort()

    n = len(delays)

    avg_delay = round(
        sum(delays) / n,
        2,
    )

    middle = n // 2

    if n % 2 == 1:

        median_delay = delays[middle]

    else:

        median_delay = round(
            (
                delays[middle - 1]
                + delays[middle]
            ) / 2,
            2,
        )

    return avg_delay, median_delay


# ================================================================
# FLIGHT COUNTS
# ================================================================

def compute_counts(conn, iata_code):
    """
    Calculate total, delayed and cancelled flights from our own
    flights table.

    The airport is identified using its IATA code.
    """

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_count,

            SUM(
                CASE
                    WHEN status = 'Delayed'
                    THEN 1
                    ELSE 0
                END
            ) AS delayed_count,

            SUM(
                CASE
                    WHEN status = 'Canceled'
                    THEN 1
                    ELSE 0
                END
            ) AS canceled_count

        FROM flights

        WHERE origin_iata = %s
           OR destination_iata = %s
        """,
        (
            iata_code,
            iata_code,
        ),
    )

    row = cursor.fetchone()

    cursor.close()

    return {
        "airport_iata": iata_code,

        "delay_date": datetime.now().strftime(
            "%Y-%m-%d"
        ),

        "total_flights": (
            row[0]
            if row and row[0]
            else 0
        ),

        "delayed_flights": (
            row[1]
            if row and row[1]
            else 0
        ),

        "avg_delay_min": 0,

        "median_delay_min": 0,

        "canceled_flights": (
            row[2]
            if row and row[2]
            else 0
        ),
    }


# ================================================================
# MAIN
# ================================================================

def main():

    print()
    print("-" * 65)
    print("FETCHING AIRPORT DELAY STATISTICS")
    print("-" * 65)

    conn = db_manager.get_connection()

    successful = 0
    live_delay_data = 0

    try:

        for icao_code in AIRPORT_CODES:

            # ----------------------------------------------------
            # Convert ICAO -> IATA
            # ----------------------------------------------------

            iata_code = get_iata_code(
                conn,
                icao_code,
            )

            if not iata_code:

                print(
                    f"  [DB ERROR] {icao_code}: "
                    f"IATA code not found in airport table."
                )

                continue

            # ----------------------------------------------------
            # Call AeroDataBox using ICAO
            # ----------------------------------------------------

            raw = api_client.get_airport_delays(
                icao_code
            )

            if raw:

                print(
                    f"  [API] {icao_code} "
                    f"({iata_code}): "
                    f"live delay data available"
                )

                live_delay_data += 1

            else:

                print(
                    f"  [NO LIVE DATA] {icao_code} "
                    f"({iata_code}): "
                    f"/delays endpoint unavailable"
                )

            # ----------------------------------------------------
            # Calculate counts from our database
            # ----------------------------------------------------

            parsed = compute_counts(
                conn,
                iata_code,
            )

            # ----------------------------------------------------
            # Calculate delay minutes
            # ----------------------------------------------------

            (
                avg_delay_min,
                median_delay_min,
            ) = compute_delay_minutes(
                conn,
                iata_code,
            )

            parsed["avg_delay_min"] = avg_delay_min

            parsed["median_delay_min"] = median_delay_min

            # ----------------------------------------------------
            # Remove previous record for same airport/date
            # ----------------------------------------------------

            cursor = conn.cursor()

            cursor.execute(
                """
                DELETE FROM airport_delays
                WHERE airport_iata = %s
                  AND delay_date = %s
                """,
                (
                    parsed["airport_iata"],
                    parsed["delay_date"],
                ),
            )

            cursor.close()

            # ----------------------------------------------------
            # Insert new delay record
            # ----------------------------------------------------

            db_manager.upsert_delay(
                conn,
                parsed,
            )

            conn.commit()

            # ----------------------------------------------------
            # Output
            # ----------------------------------------------------

            avg_display = (
                parsed["avg_delay_min"]
                if parsed["avg_delay_min"] is not None
                else "N/A"
            )

            median_display = (
                parsed["median_delay_min"]
                if parsed["median_delay_min"] is not None
                else "N/A"
            )

            print(
                f"  SUCCESS: {icao_code} ({iata_code}) | "
                f"total={parsed['total_flights']} | "
                f"delayed={parsed['delayed_flights']} | "
                f"cancelled={parsed['canceled_flights']} | "
                f"avg_delay={avg_display}min | "
                f"median_delay={median_display}min"
            )

            successful += 1

            # ----------------------------------------------------
            # API rate limit protection
            # ----------------------------------------------------

            time.sleep(2)

    finally:

        conn.close()

    print()
    print("-" * 65)
    print("DELAY FETCH COMPLETED")
    print("-" * 65)

    print(
        f"Rows written:        {successful}"
    )

    print(
        f"  with live /delays: {live_delay_data}"
    )

    print(
        f"  no live /delays:   "
        f"{successful - live_delay_data}"
    )

    print("-" * 65)


# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":
    main()