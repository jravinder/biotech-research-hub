"""Biotech Research Hub — Data Fetcher

Pulls fresh data from all public sources and writes data.json.

Sources:
  - PubMed (papers)
  - ClinicalTrials.gov (active trials)
  - RSS feeds (community news)
  - Open Targets (drug-target associations)

All disease-specific values read from config.yaml.
"""

import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import config

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_FILE = DATA_DIR / "data.json"

PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
CT_API = "https://clinicaltrials.gov/api/v2/studies"

# Read from config
INCLUDE_TERMS = config["search"]["include_terms"]
PRIORITY_TERMS = config["search"]["priority_terms"]
EXCLUDE_TERMS = config["search"]["exclude_terms"]
RELEVANCE_THRESHOLD = config["search"]["relevance_threshold"]
DISEASE_NAME = config["disease"]["name"]
SHORT_NAME = config["disease"]["short_name"]


def _xml_text(element) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _score_relevance(title, abstract, journal, keywords):
    """Score whether a paper is relevant to the configured disease."""
    haystack = " ".join([title, abstract, journal, " ".join(keywords)]).lower()
    score = 0
    reasons = []

    for term, weight in INCLUDE_TERMS.items():
        if term.lower() in haystack:
            score += weight
            reasons.append(f"+{term}")

    for term, weight in PRIORITY_TERMS.items():
        if term.lower() in haystack:
            score += weight

    for term, weight in EXCLUDE_TERMS.items():
        if term.lower() in haystack:
            score -= weight
            reasons.append(f"-{term}")

    # Boost if disease name appears in title
    if DISEASE_NAME.lower() in title.lower():
        score += 3
    if DISEASE_NAME.lower() in abstract.lower():
        score += 2

    return score, reasons


def fetch_pubmed(query=None, days=None, max_results=None):
    """Fetch recent papers from PubMed."""
    query = query or config["search"]["pubmed_query"]
    days = days or config["search"]["days"]
    max_results = max_results or config["search"]["max_results"]

    if not query:
        print(f"  PubMed: no search query configured, skipping")
        return []

    print(f"  PubMed: searching (last {days} days)...")
    min_date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    max_date = datetime.now().strftime("%Y/%m/%d")

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results * 3,
        "sort": "relevance",
        "datetype": "pdat",
        "mindate": min_date,
        "maxdate": max_date,
        "retmode": "json",
    }
    try:
        resp = requests.get(PUBMED_SEARCH, params=params, timeout=30)
        resp.raise_for_status()
        pmids = resp.json().get("esearchresult", {}).get("idlist", [])
        print(f"  PubMed: found {len(pmids)} papers")

        if not pmids:
            return []

        resp2 = requests.get(PUBMED_FETCH, params={
            "db": "pubmed", "id": ",".join(pmids), "retmode": "xml"
        }, timeout=60)
        resp2.raise_for_status()

        root = ET.fromstring(resp2.text)
        papers = []
        skipped = []
        for article in root.findall(".//PubmedArticle"):
            medline = article.find(".//MedlineCitation")
            art = medline.find(".//Article")
            pmid = medline.findtext(".//PMID", "")
            title = _xml_text(art.find(".//ArticleTitle"))
            abstract_parts = art.findall(".//Abstract/AbstractText")
            abstract = " ".join(_xml_text(t) for t in abstract_parts).strip()[:500]
            journal = art.findtext(".//Journal/Title", "")
            kw_list = medline.findall(".//KeywordList/Keyword")
            keywords = [_xml_text(kw) for kw in kw_list if _xml_text(kw)]

            pub_date_el = art.find(".//Journal/JournalIssue/PubDate")
            pub_date = ""
            if pub_date_el is not None:
                year = pub_date_el.findtext("Year", "")
                month = pub_date_el.findtext("Month", "")
                pub_date = f"{year} {month}".strip()

            author_list = art.findall(".//AuthorList/Author")
            authors = ", ".join(
                f"{a.findtext('LastName', '')} {a.findtext('Initials', '')}"
                for a in author_list[:3]
            )

            score, reasons = _score_relevance(title, abstract, journal, keywords)
            if score < RELEVANCE_THRESHOLD:
                skipped.append((pmid, title[:80], score, reasons[:3]))
                continue

            papers.append({
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "journal": journal,
                "pub_date": pub_date,
                "authors": authors,
                "keywords": keywords[:8],
                "relevance_score": score,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            })
        papers.sort(key=lambda p: (p.get("relevance_score", 0), p.get("pub_date", "")), reverse=True)
        papers = papers[:max_results]
        print(f"  PubMed: kept {len(papers)} relevant papers")
        if skipped:
            sample = "; ".join(f"{pmid}:{score}" for pmid, _, score, _ in skipped[:5])
            print(f"  PubMed: skipped {len(skipped)} weak matches ({sample})")
        return papers
    except Exception as e:
        print(f"  PubMed ERROR: {e}")
        return []


def fetch_trials(condition=None, max_results=30):
    """Fetch active clinical trials from ClinicalTrials.gov."""
    condition = condition or config["disease"]["condition_search_term"]
    if not condition:
        print("  ClinicalTrials.gov: no condition configured, skipping")
        return []

    print(f"  ClinicalTrials.gov: searching '{condition}'...")
    params = {
        "query.cond": condition,
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION",
        "pageSize": max_results,
        "format": "json",
    }
    try:
        resp = requests.get(CT_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        trials = []
        for study in data.get("studies", []):
            proto = study.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            design = proto.get("designModule", {})
            sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
            arms = proto.get("armsInterventionsModule", {})

            interventions = arms.get("interventions", [])
            intervention_names = [i.get("name", "") for i in interventions[:3]]
            phases = design.get("phases", [])
            enrollment_info = design.get("enrollmentInfo", {})
            enrollment = enrollment_info.get("count", 0) if isinstance(enrollment_info, dict) else 0

            nct_id = ident.get("nctId", "")
            trials.append({
                "nct_id": nct_id,
                "title": ident.get("briefTitle", ""),
                "status": status_mod.get("overallStatus", ""),
                "phase": ", ".join(phases) if phases else "N/A",
                "sponsor": sponsor_mod.get("leadSponsor", {}).get("name", ""),
                "intervention": "; ".join(intervention_names),
                "enrollment": enrollment,
                "url": f"https://clinicaltrials.gov/study/{nct_id}",
                "start_date": status_mod.get("startDateStruct", {}).get("date", ""),
            })

        print(f"  ClinicalTrials.gov: found {len(trials)} active trials")
        return trials
    except Exception as e:
        print(f"  ClinicalTrials.gov ERROR: {e}")
        return []


def fetch_rss_feeds():
    """Fetch latest articles from configured RSS feeds."""
    feeds = config["community_news"]["rss_feeds"]
    if not feeds:
        return []

    all_articles = []
    for feed in feeds:
        name = feed.get("name", "RSS")
        url = feed.get("url", "")
        if not url:
            continue

        print(f"  {name}: fetching RSS feed...")
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)

            for item in root.findall(".//item")[:10]:
                all_articles.append({
                    "title": item.findtext("title", ""),
                    "link": item.findtext("link", ""),
                    "pub_date": item.findtext("pubDate", ""),
                    "description": (item.findtext("description", "") or "")[:300],
                    "source": name,
                })
            print(f"  {name}: found {len(all_articles)} articles")
        except Exception as e:
            print(f"  {name} ERROR: {e}")

    return all_articles


def fetch_open_targets():
    """Fetch disease-associated targets from Open Targets."""
    mondo_id = config["disease"]["mondo_id"]
    if not mondo_id:
        print("  Open Targets: no MONDO ID configured, skipping")
        return []

    print(f"  Open Targets: fetching associations for {mondo_id}...")
    query = f"""
    query {{
      disease(efoId: "{mondo_id}") {{
        name
        associatedTargets(page: {{size: 20}}) {{
          rows {{
            target {{ approvedSymbol approvedName }}
            score
          }}
        }}
      }}
    }}
    """
    try:
        resp = requests.post(
            "https://api.platform.opentargets.org/api/v4/graphql",
            json={"query": query},
            timeout=15,
        )
        if resp.ok:
            data = resp.json().get("data", {}).get("disease", {})
            rows = data.get("associatedTargets", {}).get("rows", [])
            targets = []
            for r in rows:
                t = r.get("target", {})
                targets.append({
                    "symbol": t.get("approvedSymbol", ""),
                    "name": t.get("approvedName", ""),
                    "score": round(r.get("score", 0), 3),
                })
            print(f"  Open Targets: found {len(targets)} associated targets")
            return targets
    except Exception as e:
        print(f"  Open Targets ERROR: {e}")
    return []


def run():
    """Fetch all sources and write data.json."""
    app_name = config["branding"]["app_name"]
    print(f"\n{'='*50}")
    print(f"{app_name} Data Fetcher")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "last_updated": datetime.now().isoformat(),
        "disease": config["disease"]["name"],
        "papers": fetch_pubmed(),
        "trials": fetch_trials(),
        "community_news": fetch_rss_feeds(),
        "targets": fetch_open_targets(),
    }

    data["stats"] = {
        "papers_count": len(data["papers"]),
        "trials_count": len(data["trials"]),
        "news_count": len(data["community_news"]),
        "targets_count": len(data["targets"]),
        "total_enrollment": sum(t.get("enrollment", 0) for t in data["trials"]),
        "recruiting_count": sum(1 for t in data["trials"] if t.get("status") == "RECRUITING"),
    }

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\n{'='*50}")
    print(f"Results saved to {DATA_FILE}")
    print(f"  Papers: {data['stats']['papers_count']}")
    print(f"  Trials: {data['stats']['trials_count']} ({data['stats']['recruiting_count']} recruiting)")
    print(f"  News: {data['stats']['news_count']}")
    print(f"  Targets: {data['stats']['targets_count']}")
    print(f"  Total patients enrolled: {data['stats']['total_enrollment']}")
    print(f"{'='*50}\n")

    return data


if __name__ == "__main__":
    run()
