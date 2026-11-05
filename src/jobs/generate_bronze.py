"""Databricks job entrypoint: write synthetic raw data to the bronze layer.

Standard library only (no Faker), so it runs on serverless without PyPI access. Seeded, so every
run produces the same data and the pipeline stays idempotent. All PII is fake by construction:
national IDs use the never-issued 900 area, cards are 16 random digits, phones use 555.

Raw data is deliberately messy so silver has real work to do: duplicate customer records,
untrimmed mixed-case emails, unknown countries, formatted card numbers, test orders, duplicate
orders and orders for customers that do not exist.

Rows are generated lazily and written in chunks, so the same seeded stream scales from the default
5k customers / 50k orders to a 1M / 10M scale run without holding it in driver memory (only the
customer -> country map is kept). Sizes are job parameters on lakehouse_pipeline.
"""

from __future__ import annotations

import argparse
import random
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from itertools import islice

AS_OF = datetime(2026, 10, 1)
COUNTRIES = {  # country -> calling code; silver maps country -> region
    "US": "1", "CA": "1", "BR": "55", "MX": "52",
    "GB": "44", "DE": "49", "FR": "33", "ES": "34", "NL": "31",
    "JP": "81", "AU": "61", "IN": "91", "SG": "65",
}
FIRST = ["Ana", "Ben", "Chen", "Dara", "Eli", "Fatima", "Gabriel", "Hana", "Ivan", "Julia", "Kenji",
         "Lucia", "Mateo", "Nadia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tariq", "Uma", "Victor"]
LAST = ["Silva", "Smith", "Muller", "Garcia", "Tanaka", "Okafor", "Rossi", "Dubois", "Kim", "Patel",
        "Nguyen", "Jansen", "Lopez", "Brown", "Novak", "Haddad", "Costa", "Ito", "Wilson", "Khan"]
STREETS = ["Main St", "Oak Ave", "High St", "Park Rd", "Station Rd", "Rua Augusta", "Hauptstrasse"]
CURRENCY = {"US": "USD", "CA": "CAD", "BR": "BRL", "MX": "MXN", "GB": "GBP", "JP": "JPY", "AU": "AUD",
            "IN": "INR", "SG": "SGD"}  # everything else EUR

CUSTOMER_COLUMNS = ("customer_id", "first_name", "last_name", "email", "phone", "date_of_birth",
                    "national_id", "street", "city", "country_code", "signup_ts", "_ingested_at")
ORDER_COLUMNS = ("order_id", "customer_id", "order_ts", "amount", "currency", "card_number", "status",
                 "_ingested_at")


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def iter_customers(n: int, rng: random.Random) -> Iterator[tuple]:
    for i in range(1, n + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        country = "XX" if rng.random() < 0.005 else rng.choice(list(COUNTRIES))
        signup = AS_OF - timedelta(days=rng.randint(30, 1500), seconds=rng.randint(0, 86399))
        email = f"{first}.{last}{i}@example.com"
        if rng.random() < 0.2:
            email = f"  {email.upper()} "
        row = [
            f"C{i:06d}", first, last, email,
            f"+{COUNTRIES.get(country, '1')} 555 {rng.randint(0, 9999):04d}",
            (AS_OF - timedelta(days=rng.randint(18 * 365, 80 * 365))).strftime("%Y-%m-%d"),
            f"900-{rng.randint(10, 99)}-{rng.randint(0, 9999):04d}",
            f"{rng.randint(1, 999)} {rng.choice(STREETS)}", f"City{rng.randint(1, 50)}", country,
            _ts(signup), _ts(signup + timedelta(hours=1)),
        ]
        yield tuple(row)
        if rng.random() < 0.03:  # re-ingested later with a changed email: silver keeps the latest
            row[3] = f"{first}.{last}.new{i}@example.com"
            row[11] = _ts(signup + timedelta(days=rng.randint(1, 20)))
            yield tuple(row)


def iter_orders(n: int, countries: dict[str, str], rng: random.Random) -> Iterator[tuple]:
    """Orders for the customer -> country map (insertion order = first appearance of each customer)."""
    ids = list(countries)
    for i in range(1, n + 1):
        customer = f"C{len(ids) + 1 + i:06d}" if rng.random() < 0.01 else rng.choice(ids)  # 1% orphans
        country = countries.get(customer, "US")
        ts = AS_OF - timedelta(days=rng.randint(0, 720), seconds=rng.randint(0, 86399))
        card = "".join(str(rng.randint(0, 9)) for _ in range(16))
        if rng.random() < 0.3:
            card = " ".join(card[k:k + 4] for k in range(0, 16, 4))
        row = (f"O{i:07d}", customer, _ts(ts), f"{rng.uniform(5, 500):.2f}", CURRENCY.get(country, "EUR"),
               card, "test" if rng.random() < 0.01 else "completed", _ts(ts + timedelta(minutes=5)))
        yield row
        if rng.random() < 0.005:  # delivered twice by the source
            yield row


def generate_customers(n: int, rng: random.Random) -> list[tuple]:
    return list(iter_customers(n, rng))


def generate_orders(n: int, customers: list[tuple], rng: random.Random) -> list[tuple]:
    return list(iter_orders(n, {c[0]: c[9] for c in customers}, rng))


def chunks(rows: Iterable[tuple], size: int) -> Iterator[list[tuple]]:
    it = iter(rows)
    while batch := list(islice(it, size)):
        yield batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--customers", type=int, default=5_000)
    parser.add_argument("--orders", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=42)
    # Rows per write. Keeps each Spark Connect local relation well under the gRPC message limit.
    parser.add_argument("--chunk-size", type=int, default=200_000)
    args = parser.parse_args()

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.getOrCreate()
    rng = random.Random(args.seed)
    countries: dict[str, str] = {}

    def remember(rows: Iterator[tuple]) -> Iterator[tuple]:
        for row in rows:
            countries.setdefault(row[0], row[9])
            yield row

    def write(rows: Iterator[tuple], columns: tuple[str, ...], table: str) -> None:
        total, started = 0, datetime.now()
        for k, batch in enumerate(chunks(rows, args.chunk_size)):
            df = spark.createDataFrame(batch, schema=", ".join(f"{c} STRING" for c in columns))
            df = df.withColumn("_ingested_at", F.to_timestamp("_ingested_at"))
            writer = df.write.mode("append") if k else df.write.mode("overwrite").option("overwriteSchema", "true")
            writer.saveAsTable(table)
            total += len(batch)
        print(f"[ok] [bronze] {table}: {total} rows in {(datetime.now() - started).total_seconds():.0f}s")

    # Customers must be exhausted before orders start: both draw from the same seeded stream.
    write(remember(iter_customers(args.customers, rng)), CUSTOMER_COLUMNS,
          f"{args.catalog}.customer_bronze.customers_raw")
    write(iter_orders(args.orders, countries, rng), ORDER_COLUMNS, f"{args.catalog}.sales_bronze.orders_raw")


if __name__ == "__main__":
    main()
