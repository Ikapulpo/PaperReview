"""Central configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # PubMed
    ncbi_api_key: str = os.getenv("NCBI_API_KEY", "")
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    pubmed_search_batch: int = 100

    # Notion
    notion_api_key: str = os.getenv("NOTION_API_KEY", "")
    notion_database_id: str = os.getenv("NOTION_DATABASE_ID", "")

    # Schedule
    schedule_day: str = os.getenv("SCHEDULE_DAY", "monday")
    schedule_time: str = os.getenv("SCHEDULE_TIME", "09:00")

    # Research interests for scoring
    research_interests: list[dict] = field(default_factory=lambda: [
        {
            "name": "NKT恒常性維持機能",
            "name_en": "NKT homeostasis",
            "keywords": [
                "NKT cell homeostasis", "iNKT homeostasis",
                "NKT cell maintenance", "NKT survival",
                "NKT cell development", "thymic NKT",
                "NKT cell regulation", "NKT tolerance",
                "invariant NKT", "Vα14", "Vα24",
                "CD1d", "lipid antigen", "α-GalCer",
                "NKT cell subset", "NKT1", "NKT2", "NKT17",
                "PLZF", "T-bet", "RORγt",
                "NKT cell proliferation", "NKT cell apoptosis",
                "NKT cell turnover", "tissue-resident NKT",
            ],
            "weight": 1.0,
        },
        {
            "name": "NKTワクチン",
            "name_en": "NKT vaccine",
            "keywords": [
                "NKT vaccine", "NKT cell therapy",
                "NKT immunotherapy", "NKT adjuvant",
                "α-GalCer vaccine", "NKT anti-tumor",
                "NKT cancer", "NKT cell activation",
                "dendritic cell NKT", "NKT cytokine",
                "IFN-γ NKT", "IL-4 NKT", "IL-12 NKT",
                "NKT cell clinical", "NKT cell trial",
                "NKT adoptive transfer", "NKT cell expansion",
                "CAR-NKT", "chimeric antigen receptor NKT",
                "NKT cell immunosurveillance",
            ],
            "weight": 1.0,
        },
        {
            "name": "整形外科",
            "name_en": "Orthopedics",
            "keywords": [
                "orthopedic", "orthopaedic",
                "fracture", "bone healing",
                "joint", "cartilage", "synovial",
                "osteoarthritis", "rheumatoid arthritis",
                "spine", "intervertebral disc",
                "tendon", "ligament", "meniscus",
                "implant", "prosthesis",
                "musculoskeletal", "skeletal muscle",
                "NKT bone", "NKT joint", "NKT cartilage",
                "immune bone", "inflammation bone",
            ],
            "weight": 0.8,
        },
        {
            "name": "骨代謝",
            "name_en": "Bone metabolism",
            "keywords": [
                "bone metabolism", "bone remodeling",
                "osteoclast", "osteoblast", "osteocyte",
                "RANKL", "OPG", "osteoprotegerin",
                "bone mineral density", "osteoporosis",
                "bone marrow", "hematopoietic",
                "calcium metabolism", "vitamin D",
                "PTH", "parathyroid",
                "Wnt signaling bone", "BMP",
                "bone formation", "bone resorption",
                "NKT osteoclast", "NKT bone marrow",
                "immune bone metabolism", "osteoimmunology",
            ],
            "weight": 0.9,
        },
    ])


config = Config()
