"""Central configuration loaded from environment variables."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # PubMed
    ncbi_api_key: str = os.getenv("NCBI_API_KEY", "")
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    pubmed_search_batch: int = 100

    # Notion (NKT)
    notion_api_key: str = os.getenv("NOTION_API_KEY", "")
    notion_database_id: str = os.getenv(
        "NOTION_DATABASE_ID", "a1f5b30f-0402-4ddf-a872-c42622d9c27c"
    )

    # Notion (Spine)
    spine_notion_database_id: str = os.getenv("SPINE_NOTION_DATABASE_ID", "")

    # Schedule (NKT)
    schedule_day: str = os.getenv("SCHEDULE_DAY", "monday")
    schedule_time: str = os.getenv("SCHEDULE_TIME", "09:00")

    # Schedule (Spine)
    spine_schedule_day: str = os.getenv("SPINE_SCHEDULE_DAY", "monday")
    spine_schedule_time: str = os.getenv("SPINE_SCHEDULE_TIME", "08:00")


config = Config()
