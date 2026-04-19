"""PubMed client for spine journal paper search.

Searches papers from: Spine, The Spine Journal, European Spine Journal,
JNS: Spine, Global Spine Journal, JBJS.
"""

from src.pubmed.client import PubMedClient

SPINE_JOURNAL_QUERY = (
    '"Spine (Phila Pa 1976)"[Journal] OR '
    '"The spine journal : official journal of the North American Spine Society"[Journal] OR '
    '"European spine journal : official publication of the European Spine Society, '
    'the European Spinal Deformity Society, and the European Section of the '
    'Cervical Spine Research Society"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '"The Journal of bone and joint surgery. American volume"[Journal]'
)


class SpinePubMedClient(PubMedClient):
    """PubMed client that searches spine-specific journals."""

    def search_recent(self, days: int = 7) -> list[str]:
        from datetime import datetime, timedelta
        from src.config import config
        import logging

        logger = logging.getLogger(__name__)

        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        date_to = datetime.now().strftime("%Y/%m/%d")

        params = self._build_params(
            db="pubmed",
            term=SPINE_JOURNAL_QUERY,
            datetype="pdat",
            mindate=date_from,
            maxdate=date_to,
            retmax=config.pubmed_search_batch,
            retmode="json",
            sort="pub_date",
        )

        resp = self._request_with_retry(f"{self.base_url}/esearch.fcgi", params)
        data = resp.json()

        id_list = data.get("esearchresult", {}).get("idlist", [])
        total = data.get("esearchresult", {}).get("count", "0")
        logger.info(f"Spine journal search: found {total} papers, retrieved {len(id_list)} PMIDs")
        return id_list

    def search_and_fetch(self, days: int = 7):
        import logging
        logger = logging.getLogger(__name__)
        pmids = self.search_recent(days=days)
        if not pmids:
            logger.info("No new spine journal papers found.")
            return []
        papers = self.fetch_details(pmids)
        logger.info(f"Fetched details for {len(papers)} spine papers")
        return papers
