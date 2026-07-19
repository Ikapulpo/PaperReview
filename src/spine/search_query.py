"""Spine-journal PubMed search query and journal filter."""

SPINE_SEARCH_QUERY = (
    '('
    '"Spine"[Journal] OR '
    '"The spine journal"[Journal] OR '
    '"European spine journal"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '"The Journal of bone and joint surgery. American volume"[Journal]'
    ') AND spine'
)

TARGET_JOURNALS = {
    "Spine",
    "The spine journal",
    "The Spine Journal",
    "European spine journal",
    "European Spine Journal",
    "Journal of neurosurgery. Spine",
    "Journal of Neurosurgery: Spine",
    "Global spine journal",
    "Global Spine Journal",
    "The Journal of bone and joint surgery. American volume",
    "JBJS",
    "The Journal of Bone and Joint Surgery",
}

JOURNAL_ABBREV = {
    "Spine": "Spine",
    "The spine journal": "Spine J",
    "The Spine Journal": "Spine J",
    "European spine journal": "Eur Spine J",
    "European Spine Journal": "Eur Spine J",
    "Journal of neurosurgery. Spine": "JNS:Spine",
    "Journal of Neurosurgery: Spine": "JNS:Spine",
    "Global spine journal": "GSJ",
    "Global Spine Journal": "GSJ",
    "The Journal of bone and joint surgery. American volume": "JBJS",
    "The Journal of Bone and Joint Surgery": "JBJS",
}


def abbreviate_journal(journal_name: str) -> str:
    return JOURNAL_ABBREV.get(journal_name, journal_name)
