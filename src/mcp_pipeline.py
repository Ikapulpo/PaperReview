"""MCP-based pipeline for Claude Code automated weekly NKT paper review.

This module defines the prompt and scoring logic used when the pipeline
is executed via Claude Code's MCP tools (PubMed MCP + Notion MCP) rather
than the standalone Python client.  The CronCreate durable task fires
this prompt weekly.

Research focus areas for scoring:
  1. NKT homeostasis / iNKT development
  2. NKT vaccines / tumor immunity / CAR-NKT
  3. Orthopedic surgery / bone metabolism / osteoimmunology
  4. Methods & concepts applicable to the lab
"""

# Database and data source IDs for Notion "週刊NKT（メルマガ）"
NOTION_DATABASE_ID = "a1f5b30f-0402-4ddf-a872-c42622d9c27c"
NOTION_DATA_SOURCE_ID = "5e5eca70-b1c4-4039-92fe-a92fcf8d21a0"

PUBMED_QUERY = (
    '("NKT cell" OR "NKT cells" OR "natural killer T cell" OR '
    '"natural killer T cells" OR "iNKT" OR "invariant NKT" OR '
    '"Vα14" OR "Valpha14" OR "Vα24" OR "Valpha24" OR '
    '"CD1d-restricted" OR "CD1d restricted") '
    'AND ("mouse" OR "mice" OR "murine" OR "human" OR "patient" OR "clinical")'
)

RESEARCH_INTERESTS = """
Our lab's core research areas (for relevance scoring):

1. **NKT cell homeostasis** — How iNKT cells are maintained in steady state,
   tissue-resident NKT biology, NKT cell development/maturation/survival,
   PLZF, NKT subsets (NKT1/2/17), thymic selection.

2. **NKT vaccines & cell therapy** — α-GalCer-based vaccines, CAR-NKT,
   NKT-mediated anti-tumor immunity, NKT activation for immunotherapy,
   dendritic cell–NKT cross-talk, clinical trials.

3. **Orthopedic surgery & bone metabolism** — Osteoimmunology, osteoclast/
   osteoblast regulation, RANKL/OPG, bone remodeling, fracture healing,
   osteoporosis, arthroplasty, bone marrow niche, immune–bone interaction.

4. **NKT–B cell interaction** — NKT help for B cells, germinal center
   responses, B cell tolerance, CXCR6/CXCL16 axis.

Scoring criteria:
  - How directly the paper's METHODS could be applied in our lab
  - How the paper's CONCEPTS connect to our research questions
  - Whether the paper provides new mechanistic insights for NKT biology
  - Relevance to ongoing projects (score higher if directly applicable)

Papers about NK/T-cell lymphoma (NKTCL/ENKTL) score very low (0.05)
unless they contain insights relevant to NKT cell biology.
"""

WEEKLY_REVIEW_PROMPT = f"""
You are running the weekly NKT cell paper review pipeline.

## Step 1: Search PubMed
Search for NKT cell papers published in the last 7 days using:
- Query: {PUBMED_QUERY}
- Date range: last 7 days (publication date)
- Sort by: pub_date
- Max results: 50

## Step 2: Get article metadata
Fetch full metadata for all found PMIDs.

## Step 3: Deduplicate
Check the latest issues in the Notion database (ID: {NOTION_DATABASE_ID})
for existing PMIDs. Skip any papers already covered.

## Step 4: AI-powered scoring & analysis
For each new paper, analyze:
{RESEARCH_INTERESTS}

Score each paper 0.0–1.0 and assign topic tags from:
  iNKT development, Thymus / development, NKT-B cell, B cell tolerance,
  Osteoimmunology, Autoimmunity / SLE, Metabolism, Tumor immunity,
  Infection, Cytokines (IL-4/IFNγ), TCR repertoire, Methods / Omics,
  scRNA-seq / spatial

For each paper write:
- 【概要】Japanese summary of key findings
- 【当研究室への示唆】How methods/concepts connect to our research

## Step 5: Post to Notion
Create a new page in the 週刊NKT（メルマガ）database
(data_source_id: {NOTION_DATA_SOURCE_ID}) with:
- Issue title: Vol.XX — 2026-WXX
- Week: Monday of current week
- Status: Draft
- Source: Claude Code
- Topics: aggregated from all papers
- Full newsletter content with callout, topic summary, per-paper sections

## Step 6: Notify
Send a PushNotification summarizing the results.
"""
