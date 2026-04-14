"""Biotech Research Hub — Site Builder

Render a minimal config-driven homepage from config.yaml + data/data.json.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import load_config

ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT / "templates"
DATA_FILE = ROOT / "data" / "data.json"
OUTPUT_FILE = ROOT / "index.html"


def load_data():
    """Load fetched data when available, otherwise return an empty shell."""
    if not DATA_FILE.exists():
        return {
            "last_updated": "",
            "papers": [],
            "trials": [],
            "community_news": [],
            "targets": [],
            "stats": {
                "papers_count": 0,
                "trials_count": 0,
                "news_count": 0,
                "targets_count": 0,
                "total_enrollment": 0,
                "recruiting_count": 0,
            },
        }

    with open(DATA_FILE) as f:
        return json.load(f)


def format_timestamp(iso_string):
    """Render ISO timestamps into a simple readable string."""
    if not iso_string:
        return "No data fetched yet"
    try:
        return datetime.fromisoformat(iso_string).strftime("%B %d, %Y at %I:%M %p")
    except ValueError:
        return iso_string


def build_page(config, data):
    """Render the homepage."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("index.html.j2")

    top_papers = data.get("papers", [])[:6]
    top_trials = data.get("trials", [])[:6]
    support_orgs = config.get("branding", {}).get("support_orgs", [])
    targets = config.get("targets", [])[:6]

    return template.render(
        config=config,
        data=data,
        stats=data.get("stats", {}),
        top_papers=top_papers,
        top_trials=top_trials,
        targets=targets,
        support_orgs=support_orgs,
        last_updated_label=format_timestamp(data.get("last_updated", "")),
    )


def main():
    parser = argparse.ArgumentParser(description="Render a config-driven disease homepage.")
    parser.add_argument("--config", help="Path to config file", default=None)
    parser.add_argument("--output", help="Path to output HTML file", default=str(OUTPUT_FILE))
    args = parser.parse_args()

    config = load_config(args.config)
    data = load_data()
    html = build_page(config, data)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)

    print(f"Rendered homepage to {output_path}")


if __name__ == "__main__":
    main()
