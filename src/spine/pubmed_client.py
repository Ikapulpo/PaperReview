"""PubMed client for spine journal paper search.

Targets: Spine, The Spine Journal, European Spine Journal,
JNS: Spine, Global Spine Journal, JBJS.
"""

import logging

from src.pubmed.client import Paper, PubMedClient
from src.config import config

logger = logging.getLogger(__name__)

SPINE_JOURNAL_QUERY = (
    '"Spine (Phila Pa 1976)"[Journal] OR '
    '"Spine J"[Journal] OR '
    '"Eur Spine J"[Journal] OR '
    '"J Neurosurg Spine"[Journal] OR '
    '"Global Spine J"[Journal] OR '
    '("J Bone Joint Surg Am"[Journal] AND '
    "(spine OR spinal OR vertebr* OR lumbar OR cervical OR thoracic "
    "OR scoliosis OR kyphosis OR disc OR spondyl*))"
)


class SpinePubMedClient(PubMedClient):
    """PubMed client targeting spine-specific journals."""

    def search_recent(self, days: int = 7) -> list[str]:
        from datetime import datetime, timedelta

        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        date_to = datetime.now().strftime("%Y/%m/%d")

        params = self._build_params(
            db="pubmed",
            term=SPINE_JOURNAL_QUERY,
            datetype="pdat",
            mindate=date_from,
            maxdate=date_to,
            retmax=200,
            retmode="json",
            sort="pub_date",
        )

        resp = self._request_with_retry(f"{self.base_url}/esearch.fcgi", params)
        data = resp.json()

        id_list = data.get("esearchresult", {}).get("idlist", [])
        total = data.get("esearchresult", {}).get("count", "0")
        logger.info(f"Spine PubMed search: found {total} papers, retrieved {len(id_list)} PMIDs")
        return id_list

    def _parse_article(self, article) -> Paper | None:
        paper = super()._parse_article(article)
        if paper is None:
            return None

        # Extract first author's affiliation
        first_author = article.find(".//Author")
        if first_author is not None:
            aff = first_author.findtext(".//Affiliation", "")
            paper.affiliation = aff

        # Extract volume and issue
        journal_issue = article.find(".//JournalIssue")
        if journal_issue is not None:
            paper.volume = journal_issue.findtext("Volume", "")
            paper.issue = journal_issue.findtext("Issue", "")

        return paper

    def search_and_fetch(self, days: int = 7) -> list[Paper]:
        pmids = self.search_recent(days=days)
        if not pmids:
            logger.info("No new spine journal papers found.")
            return []
        papers = self.fetch_details(pmids)
        logger.info(f"Fetched details for {len(papers)} spine papers")
        return papers
