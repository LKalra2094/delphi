"""Load seed JSON into Neon. Idempotent (INSERT ... ON CONFLICT DO NOTHING)."""
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
# The seeder has no .env of its own; it reuses the orchestrator's DATABASE_URL.
load_dotenv(HERE.parent / "orchestrator" / ".env")
load_dotenv()  # also honor a real env / db-local .env if present

from delphi_common.db import PostgresClient
DATASETS = [
    ("seed_reviews_store.json", "reviews_store"),
    ("seed_feedback_survey.json", "feedback_survey"),
]


async def main():
    db = PostgresClient()
    for filename, table in DATASETS:
        path = HERE / filename
        rows = json.loads(path.read_text())
        n = await db.insert_ignore(table, rows, conflict_columns=["ext_id"])
        print(f"{table}: processed {n} rows from {filename}")


if __name__ == "__main__":
    asyncio.run(main())
