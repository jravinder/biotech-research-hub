"""Biotech Research Hub — Local Autoresearch Loop

Ask one bounded research question, retrieve relevant evidence from fetched data,
generate a small set of source-backed hypotheses, score them, and write outputs
as JSON plus a markdown memo.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import config
from llm import ask_json

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "data.json"
RUNS_DIR = ROOT / "runs"


SYSTEM_PROMPT = """You are a careful research analyst helping explore disease evidence.

Rules:
- Use only the provided evidence bundle.
- Do not claim efficacy or certainty.
- Generate at most 5 bounded hypotheses.
- Every hypothesis must cite supporting source ids from the provided bundle.
- Include uncertainty and next validation steps.
- If the evidence is weak, say so clearly.

Return JSON with this shape:
{
  "question": "...",
  "summary": "...",
  "themes": ["...", "..."],
  "hypotheses": [
    {
      "title": "...",
      "mechanism": "...",
      "why_it_matters": "...",
      "supporting_source_ids": ["paper:123", "trial:NCT..."],
      "counterpoints": ["...", "..."],
      "next_steps": ["...", "..."]
    }
  ]
}
"""


DEFAULT_QUESTIONS = [
    "Which mechanisms in the recent evidence look strongest for disease-modifying intervention?",
    "Which repurposable drugs or modalities appear most aligned with the recent evidence?",
    "Where does the evidence show the biggest gap between mechanistic promise and clinical validation?",
]


def load_data():
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Missing data file: {DATA_FILE}. Run src/data_fetcher.py first.")
    with open(DATA_FILE) as f:
        return json.load(f)


def ensure_matching_disease(data):
    """Prevent analysis against cached data from a different disease."""
    data_disease = (data.get("disease") or "").strip()
    config_disease = (config.get("disease", {}).get("name") or "").strip()

    if not data_disease or not config_disease:
        return

    if data_disease != config_disease:
        raise ValueError(
            f"Fetched data is for '{data_disease}' but active config is '{config_disease}'. "
            "Run src/data_fetcher.py again for the selected disease before autoresearch."
        )


def tokenize(text):
    return set(re.findall(r"[a-z0-9][a-z0-9\-']+", (text or "").lower()))


def score_item(question_terms, text):
    item_terms = tokenize(text)
    return sum(1 for term in question_terms if term in item_terms)


def build_evidence_bundle(data, question, limit=12):
    question_terms = tokenize(question)
    scored = []

    for paper in data.get("papers", []):
        text = " ".join([
            paper.get("title", ""),
            paper.get("abstract", ""),
            paper.get("journal", ""),
            " ".join(paper.get("keywords", [])),
        ])
        score = score_item(question_terms, text) + int(paper.get("relevance_score", 0))
        scored.append((score, {
            "id": f"paper:{paper.get('pmid', '')}",
            "type": "paper",
            "title": paper.get("title", ""),
            "text": paper.get("abstract", ""),
            "meta": {
                "journal": paper.get("journal", ""),
                "pub_date": paper.get("pub_date", ""),
                "url": paper.get("url", ""),
            },
        }))

    for trial in data.get("trials", []):
        text = " ".join([
            trial.get("title", ""),
            trial.get("status", ""),
            trial.get("phase", ""),
            trial.get("sponsor", ""),
            trial.get("intervention", ""),
        ])
        score = score_item(question_terms, text) + 2
        scored.append((score, {
            "id": f"trial:{trial.get('nct_id', '')}",
            "type": "trial",
            "title": trial.get("title", ""),
            "text": f"{trial.get('status', '')}; {trial.get('phase', '')}; {trial.get('intervention', '')}",
            "meta": {
                "sponsor": trial.get("sponsor", ""),
                "url": trial.get("url", ""),
            },
        }))

    for item in data.get("community_news", []):
        text = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("source", ""),
        ])
        score = score_item(question_terms, text) + 1
        scored.append((score, {
            "id": f"news:{item.get('source', 'feed')}:{len(scored)}",
            "type": "news",
            "title": item.get("title", ""),
            "text": item.get("description", ""),
            "meta": {
                "source": item.get("source", ""),
                "url": item.get("link", ""),
            },
        }))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    bundle = [item for score, item in scored if score > 0][:limit]

    if not bundle:
        bundle = [item for _, item in scored[:limit]]

    return bundle


def heuristic_scores(hypothesis, evidence_lookup):
    source_ids = hypothesis.get("supporting_source_ids", [])
    evidence_types = [evidence_lookup.get(source_id, {}).get("type", "") for source_id in source_ids]
    type_counts = Counter(evidence_types)

    support_score = min(100, 20 + 15 * len(source_ids))
    diversity_bonus = 10 if len(type_counts) >= 2 else 0
    risk_penalty = min(30, 5 * len(hypothesis.get("counterpoints", [])))
    next_step_bonus = min(15, 3 * len(hypothesis.get("next_steps", [])))

    total = max(0, min(100, support_score + diversity_bonus + next_step_bonus - risk_penalty))
    return {
        "overall_score": total,
        "support_score": support_score,
        "evidence_diversity_bonus": diversity_bonus,
        "risk_penalty": risk_penalty,
    }


def render_markdown(result, evidence_lookup):
    lines = []
    lines.append(f"# Autoresearch Memo: {result['question']}")
    lines.append("")
    lines.append(f"Generated: {result['generated_at']}")
    lines.append("")
    lines.append("## Summary")
    lines.append(result.get("summary", ""))
    lines.append("")
    lines.append("## Themes")
    for theme in result.get("themes", []):
        lines.append(f"- {theme}")
    lines.append("")
    lines.append("## Hypotheses")

    for idx, hypothesis in enumerate(result.get("hypotheses", []), start=1):
        lines.append(f"### {idx}. {hypothesis.get('title', 'Untitled hypothesis')}")
        lines.append("")
        lines.append(f"**Mechanism:** {hypothesis.get('mechanism', '')}")
        lines.append("")
        lines.append(f"**Why it matters:** {hypothesis.get('why_it_matters', '')}")
        lines.append("")
        lines.append(f"**Score:** {hypothesis.get('scores', {}).get('overall_score', 0)}/100")
        lines.append("")
        lines.append("**Supporting sources**")
        for source_id in hypothesis.get("supporting_source_ids", []):
            evidence = evidence_lookup.get(source_id, {})
            title = evidence.get("title", source_id)
            url = evidence.get("meta", {}).get("url", "")
            if url:
                lines.append(f"- [{source_id}] {title} — {url}")
            else:
                lines.append(f"- [{source_id}] {title}")
        lines.append("")
        lines.append("**Counterpoints**")
        for item in hypothesis.get("counterpoints", []):
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**Next steps**")
        for item in hypothesis.get("next_steps", []):
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def run_autoresearch(question):
    data = load_data()
    ensure_matching_disease(data)
    evidence_bundle = build_evidence_bundle(data, question)
    evidence_lookup = {item["id"]: item for item in evidence_bundle}

    prompt = json.dumps({
        "disease": config["disease"]["name"],
        "question": question,
        "evidence_bundle": evidence_bundle,
    }, indent=2)

    result = ask_json(prompt, system=SYSTEM_PROMPT)
    result["question"] = question
    result["generated_at"] = datetime.now().isoformat()
    result["disease"] = config["disease"]["name"]
    result["evidence_bundle"] = evidence_bundle

    cleaned = []
    for hypothesis in result.get("hypotheses", [])[:5]:
        scores = heuristic_scores(hypothesis, evidence_lookup)
        hypothesis["scores"] = scores
        cleaned.append(hypothesis)
    result["hypotheses"] = sorted(cleaned, key=lambda item: item.get("scores", {}).get("overall_score", 0), reverse=True)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60]
    stem = f"{config['disease']['short_name'].lower()}-{slug or 'autoresearch'}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    json_path = RUNS_DIR / f"{stem}.json"
    md_path = RUNS_DIR / f"{stem}.md"

    json_path.write_text(json.dumps(result, indent=2))
    md_path.write_text(render_markdown(result, evidence_lookup))

    print(f"Wrote autoresearch JSON to {json_path}")
    print(f"Wrote autoresearch memo to {md_path}")


def main():
    parser = argparse.ArgumentParser(description="Run a bounded local autoresearch loop.")
    parser.add_argument("--question", help="Hard research question to investigate", default=None)
    parser.add_argument("--preset", type=int, choices=range(1, len(DEFAULT_QUESTIONS) + 1), help="Use one of the built-in questions")
    args = parser.parse_args()

    question = args.question
    if args.preset:
        question = DEFAULT_QUESTIONS[args.preset - 1]
    if not question:
        question = DEFAULT_QUESTIONS[0]

    run_autoresearch(question)


if __name__ == "__main__":
    main()
