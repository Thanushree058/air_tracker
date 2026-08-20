-- Diagnostic: do NULL-origin arrival rows have a "twin" flight
-- (same destination, same arrival time, different flight number,
-- but WITH an origin) -- the signature of a codeshare secondary
-- listing that AeroDataBox doesn't repeat full departure data for.
SELECT n.flight_number  AS null_origin_flight,
       n.destination_iata,
       COALESCE(n.actual_arrival, n.scheduled_arrival) AS arrival_time,
       t.flight_number  AS twin_flight_with_origin,
       t.origin_iata    AS twin_origin
FROM flights n
JOIN flights t
  ON t.destination_iata = n.destination_iata
 AND COALESCE(t.actual_arrival, t.scheduled_arrival) = COALESCE(n.actual_arrival, n.scheduled_arrival)
 AND t.origin_iata IS NOT NULL
 AND t.flight_number <> n.flight_number
WHERE n.origin_iata IS NULL
LIMIT 20;