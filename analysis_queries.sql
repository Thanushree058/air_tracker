-- ==========================================================
-- Air Tracker: Flight Analytics — Analysis Queries (fixed)
-- ==========================================================

-- 1) Total number of flights for each aircraft model
SELECT ac.model,
       COUNT(*) AS flight_count
FROM flights f
JOIN aircraft ac ON ac.registration = f.aircraft_registration
GROUP BY ac.model
ORDER BY flight_count DESC;


-- 2) Aircraft (registration, model) assigned to more than 5 flights
SELECT ac.registration,
       ac.model,
       COUNT(*) AS flight_count
FROM flights f
JOIN aircraft ac ON ac.registration = f.aircraft_registration
GROUP BY ac.registration, ac.model
HAVING COUNT(*) > 5
ORDER BY flight_count DESC;


-- 3) For each airport, name + number of outbound flights, only airports with > 5
SELECT a.name,
       COUNT(*) AS outbound_flights
FROM flights f
JOIN airport a ON a.iata_code = f.origin_iata
GROUP BY a.name
HAVING COUNT(*) > 5
ORDER BY outbound_flights DESC;


-- 4) Top 3 destination airports (name, city) by number of arriving flights
SELECT a.name,
       a.city,
       COUNT(*) AS arrivals
FROM flights f
JOIN airport a ON a.iata_code = f.destination_iata
GROUP BY a.name, a.city
ORDER BY arrivals DESC
LIMIT 3;


-- 5) Each flight: number, origin, destination, Domestic/International label
-- NOTE (bugfix): airports that only ever appear as a flight endpoint
-- (never one of the 12 monitored airports) are stored as stub rows
-- with country = NULL, since fetch_and_store_airports() only calls
-- the AeroDataBox airport-details endpoint for the monitored list.
-- The previous version's CASE only tested o.country = d.country,
-- and in SQL NULL = NULL evaluates to NULL (not TRUE), so it fell
-- through to the ELSE branch - silently mislabeling flights between
-- two unmonitored US airports (e.g. LAX -> LAS) as 'International'.
-- A flight is only genuinely classifiable once both endpoints have
-- a known country - otherwise it's reported as 'Unknown' rather than
-- guessed.
SELECT f.flight_number,
       f.origin_iata,
       f.destination_iata,
       CASE
           WHEN o.country IS NULL OR d.country IS NULL THEN 'Unknown'
           WHEN o.country = d.country THEN 'Domestic'
           ELSE 'International'
       END AS flight_type
FROM flights f
LEFT JOIN airport o ON o.iata_code = f.origin_iata
LEFT JOIN airport d ON d.iata_code = f.destination_iata;


-- 6) 5 most recent arrivals at DEL
-- NOTE: the spec asks for the departure AIRPORT NAME, not the IATA code,
-- so origin is joined against the airport table. aircraft is joined too
-- so both registration and model are available.
SELECT
    f.flight_number,
    ac.registration AS aircraft_registration,
    ac.model AS aircraft_model,
    a.name AS departure_airport,
    COALESCE(f.actual_arrival, f.scheduled_arrival) AS arrival_time
FROM flights f
LEFT JOIN aircraft ac
    ON ac.registration = f.aircraft_registration
LEFT JOIN airport a
    ON a.iata_code = f.origin_iata
WHERE f.destination_iata = 'DEL'
ORDER BY arrival_time DESC
LIMIT 5;


-- 7) Airports never used as a destination (no arriving flights)
SELECT a.iata_code, a.name
FROM airport a
WHERE a.iata_code NOT IN (
    SELECT DISTINCT destination_iata FROM flights WHERE destination_iata IS NOT NULL
);


-- 8) For each airline, count flights by status
-- AeroDataBox reports flight lifecycle statuses rather than
-- a direct "On Time" punctuality verdict.
-- Therefore Departed and Arrived are reported together as
-- departed_or_arrived instead of being labeled "on time".
-- AeroDataBox uses "Canceled" with one L.
-- other_status covers every remaining AeroDataBox lifecycle status
-- (Unknown, Expected, CheckIn, GateClosed, Approaching, etc.) plus
-- NULL statuses, so the four count columns always sum to
-- total_flights instead of silently omitting ~25-30% of flights
-- from the breakdown, as the earlier 3-bucket version did.
SELECT f.airline_code,
       SUM(CASE WHEN f.status IN ('Departed', 'Arrived') THEN 1 ELSE 0 END) AS departed_or_arrived,
       SUM(CASE WHEN f.status = 'Delayed' THEN 1 ELSE 0 END) AS delayed_count,
       SUM(CASE WHEN f.status = 'Canceled' THEN 1 ELSE 0 END) AS cancelled,
       SUM(CASE
               WHEN f.status IS NULL
                    OR f.status NOT IN ('Departed', 'Arrived', 'Delayed', 'Canceled')
               THEN 1 ELSE 0
           END) AS other_status,
       COUNT(*) AS total_flights
FROM flights f
GROUP BY f.airline_code
ORDER BY total_flights DESC;


-- 9) All cancelled flights, with aircraft and both airports, ordered by departure time desc
-- NOTE: AeroDataBox spells it 'Canceled' (one L), not 'Cancelled'.
-- NOTE (bugfix): origin/destination were INNER JOINed, so a cancelled
-- flight missing one side's airport (see codeshare_check.sql) was
-- silently dropped instead of shown - 170 cancelled flights total per
-- query 8's per-airline counts, but only 144 rows here before this
-- fix. LEFT JOIN keeps every cancelled flight - the airport name is
-- NULL only when the source data itself has no airport for that leg.
SELECT f.flight_number,
       ac.registration,
       ac.model,
       o.name AS origin_airport,
       d.name AS destination_airport,
       f.scheduled_departure
FROM flights f
LEFT JOIN aircraft ac ON ac.registration = f.aircraft_registration
LEFT JOIN airport o ON o.iata_code = f.origin_iata
LEFT JOIN airport d ON d.iata_code = f.destination_iata
WHERE f.status = 'Canceled'
ORDER BY f.scheduled_departure DESC;


-- 10) City pairs (origin-destination) with more than 2 different aircraft models
SELECT f.origin_iata,
       f.destination_iata,
       COUNT(DISTINCT ac.model) AS distinct_models
FROM flights f
JOIN aircraft ac ON ac.registration = f.aircraft_registration
WHERE f.origin_iata IS NOT NULL AND f.destination_iata IS NOT NULL
GROUP BY f.origin_iata, f.destination_iata
HAVING COUNT(DISTINCT ac.model) > 2
ORDER BY distinct_models DESC;


-- 11) For each destination airport, % of delayed flights among all arrivals
-- 'Delayed' matches AeroDataBox's real value as-is, no change needed here.
SELECT f.destination_iata,
       a.name,
       COUNT(*) AS total_arrivals,
       SUM(CASE WHEN f.status = 'Delayed' THEN 1 ELSE 0 END) AS delayed_arrivals,
       ROUND(100.0 * SUM(CASE WHEN f.status = 'Delayed' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_delayed
FROM flights f
JOIN airport a ON a.iata_code = f.destination_iata
GROUP BY f.destination_iata, a.name
ORDER BY pct_delayed DESC;