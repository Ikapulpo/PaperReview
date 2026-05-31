"""PubMed search client for spine journal papers."""

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

from src.config import config

logger = logging.getLogger(__name__)

SPINE_JOURNALS_QUERY = (
    '("Spine"[Journal] OR "The spine journal"[Journal] OR '
    '"European spine journal"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '"The Journal of bone and joint surgery. American volume"[Journal])'
)

JBJS_SPINE_FILTER = (
    '("The Journal of bone and joint surgery. American volume"[Journal] '
    'AND (spine OR spinal OR lumbar OR cervical OR thoracic OR '
    'scoliosis OR kyphosis OR vertebr* OR disc OR "fusion" OR '
    'laminectomy OR discectomy OR spondyl*))'
)

SPINE_SEARCH_QUERY = (
    '('
    '"Spine"[Journal] OR "The spine journal"[Journal] OR '
    '"European spine journal"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '("The Journal of bone and joint surgery. American volume"[Journal] '
    'AND (spine OR spinal OR lumbar OR cervical OR thoracic OR '
    'scoliosis OR kyphosis OR vertebr* OR disc OR fusion OR '
    'laminectomy OR discectomy OR spondyl*))'
    ')'
)


@dataclass
class SpinePaper:
    """Represents a spine journal paper."""
    pmid: str
    title: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    pub_date: str = ""
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    @property
    def first_author(self) -> str:
        return self.authors[0] if self.authors else "Unknown"

    @property
    def first_affiliation(self) -> str:
        return self.affiliations[0] if self.affiliations else ""

    @property
    def journal_citation(self) -> str:
        parts = [self.journal]
        if self.volume:
            parts.append(f"{self.volume}")
        if self.issue:
            parts[-1] += f"({self.issue})"
        if self.pages:
            parts.append(f": {self.pages}")
        return "".join(parts)


class SpineSearchClient:
    """Client for PubMed E-utilities API targeting spine journals."""

    def __init__(self):
        self.base_url = config.pubmed_base_url
        self.api_key = config.ncbi_api_key
        self.session = requests.Session()

    def _build_params(self, **kwargs) -> dict:
        params = dict(kwargs)
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _request_with_retry(self, url: str, params: dict, max_retries: int = 3) -> requests.Response:
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                    time.sleep(wait)
                else:
                    raise

    def search_recent(self, days: int = 7) -> list[str]:
        """Search PubMed for spine journal papers published in the last N days."""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        date_to = datetime.now().strftime("%Y/%m/%d")

        params = self._build_params(
            db="pubmed",
            term=SPINE_SEARCH_QUERY,
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
        logger.info(f"Spine journal search: found {total} papers, retrieved {len(id_list)} PMIDs")
        return id_list

    def fetch_details(self, pmids: list[str]) -> list[SpinePaper]:
        """Fetch detailed information for a list of PMIDs."""
        if not pmids:
            return []

        papers = []
        batch_size = 50
        for i in range(0, len(pmids), batch_size):
            batch = pmids[i:i + batch_size]
            batch_papers = self._fetch_batch(batch)
            papers.extend(batch_papers)
            if i + batch_size < len(pmids):
                time.sleep(0.5)

        return papers

    def _fetch_batch(self, pmids: list[str]) -> list[SpinePaper]:
        params = self._build_params(
            db="pubmed",
            id=",".join(pmids),
            retmode="xml",
        )
        resp = self._request_with_retry(f"{self.base_url}/efetch.fcgi", params)
        return self._parse_xml(resp.text)

    def _parse_xml(self, xml_text: str) -> list[SpinePaper]:
        papers = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"Failed to parse PubMed XML: {e}")
            return papers

        for article in root.findall(".//PubmedArticle"):
            try:
                paper = self._parse_article(article)
                if paper:
                    papers.append(paper)
            except Exception as e:
                pmid = article.findtext(".//PMID", "unknown")
                logger.warning(f"Failed to parse article PMID={pmid}: {e}")

        return papers

    def _parse_article(self, article) -> SpinePaper | None:
        pmid = article.findtext(".//PMID", "")
        if not pmid:
            return None

        title = article.findtext(".//ArticleTitle", "")

        # Abstract
        abstract_parts = []
        for abs_text in article.findall(".//AbstractText"):
            label = abs_text.get("Label", "")
            text = "".join(abs_text.itertext())
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        # Authors and affiliations
        authors = []
        affiliations = []
        for author in article.findall(".//Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {fore}".strip())
            for aff in author.findall(".//AffiliationInfo/Affiliation"):
                if aff.text and aff.text not in affiliations:
                    affiliations.append(aff.text)

        # Journal details
        journal = article.findtext(".//Journal/Title", "")
        volume = article.findtext(".//Journal/JournalIssue/Volume", "")
        issue = article.findtext(".//Journal/JournalIssue/Issue", "")
        pages = article.findtext(".//MedlineCitation/Article/Pagination/MedlinePgn", "")

        # Publication date
        pub_date_elem = article.find(".//PubDate")
        if pub_date_elem is not None:
            year = pub_date_elem.findtext("Year", "")
            month = pub_date_elem.findtext("Month", "")
            day = pub_date_elem.findtext("Day", "")
            pub_date = f"{year} {month} {day}".strip()
        else:
            pub_date = ""

        # DOI
        doi = ""
        for id_elem in article.findall(".//ArticleId"):
            if id_elem.get("IdType") == "doi":
                doi = id_elem.text or ""
                break

        # Keywords
        keywords = [kw.text for kw in article.findall(".//Keyword") if kw.text]

        # MeSH terms
        mesh_terms = [
            mh.findtext("DescriptorName", "")
            for mh in article.findall(".//MeshHeading")
            if mh.findtext("DescriptorName")
        ]

        return SpinePaper(
            pmid=pmid,
            title=title,
            abstract=abstract,
            authors=authors,
            affiliations=affiliations,
            journal=journal,
            volume=volume,
            issue=issue,
            pages=pages,
            pub_date=pub_date,
            doi=doi,
            keywords=keywords,
            mesh_terms=mesh_terms,
        )

    def search_and_fetch(self, days: int = 7) -> list[SpinePaper]:
        """Search for recent spine journal papers and fetch details."""
        pmids = self.search_recent(days=days)
        if not pmids:
            logger.info("No new spine journal papers found.")
            return []
        papers = self.fetch_details(pmids)
        logger.info(f"Fetched details for {len(papers)} spine papers")
        return papers
