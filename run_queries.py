"""
Run all SQL queries from analysis_queries.sql against the MySQL
air_tracker database.

Usage:
    python run_queries.py
"""

import re
import pandas as pd
import mysql.connector

from config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
)


def split_queries(sql_text: str):
    """
    Split the SQL file into individual queries.

    Each query can have comments such as:
    -- TOTAL FLIGHTS
    """

    # Remove USE air_tracker; because the connection already selects the DB
    sql_text = re.sub(
        r"^\s*USE\s+air_tracker\s*;\s*",
        "",
        sql_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Split using semicolon
    statements = sql_text.split(";")

    queries = []

    for statement in statements:
        statement = statement.strip()

        if not statement:
            continue

        # Extract the title comment for this query.
        #
        # Prefer a "-- N) ..." numbered comment line (the actual
        # per-query title used throughout analysis_queries.sql).
        # Falling back to "first comment line found" breaks for
        # Query 1 specifically: it's preceded by the file's own
        # multi-line banner comment ("-- =====...", "-- Air
        # Tracker..."), and since split_queries() only breaks on
        # literal ";" characters, that banner ends up glued onto
        # Query 1's statement text ahead of its real "-- 1) ..."
        # title line, so the first-match regex previously grabbed
        # the banner divider instead.
        title = "Query"

        numbered_match = re.search(
            r"--\s*(\d+\).+)",
            statement
        )

        if numbered_match:
            title = numbered_match.group(1).strip()
        else:
            comment_match = re.search(
                r"--\s*(.+)",
                statement
            )

            if comment_match:
                title = comment_match.group(1).strip()

        # Remove SQL comments
        sql = re.sub(
            r"--.*",
            "",
            statement
        ).strip()

        if sql:
            queries.append((title, sql))

    return queries


def main():

    print("Connecting to MySQL...")

    conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

    print("Connected successfully to MySQL database:", DB_NAME)

    with open("analysis_queries.sql", "r", encoding="utf-8") as f:
        sql_text = f.read()

    queries = split_queries(sql_text)

    output_lines = []

    print(f"\nFound {len(queries)} SQL queries.\n")

    for i, (title, sql) in enumerate(queries, start=1):

        header = f"\n{'=' * 60}\nQuery {i}: {title}\n{'=' * 60}"

        print(header)
        output_lines.append(header)

        try:

            df = pd.read_sql(
                sql,
                conn
            )

            if df.empty:
                print("No results.")
                output_lines.append("No results.")
            else:
                result = df.to_string(index=False)

                print(result)
                output_lines.append(result)

        except Exception as e:

            error_message = (
                f"[ERROR running query {i}]\n"
                f"{e}\n"
                f"SQL: {sql}"
            )

            print(error_message)
            output_lines.append(error_message)

    conn.close()

    with open(
        "query_results.txt",
        "w",
        encoding="utf-8"
    ) as f:

        f.write("\n".join(output_lines))

    print("\n" + "=" * 60)
    print("All queries completed.")
    print("Results saved to query_results.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()