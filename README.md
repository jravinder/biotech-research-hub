# Biotech Research Hub

An open, configurable disease research workspace powered by Gemma.

This repo is the template layer behind disease-specific hubs like HD Research Hub. The goal is simple: help someone stand up a useful research workspace for a disease without rebuilding the stack from scratch.

It combines:
- public-source gathering from PubMed, ClinicalTrials.gov, RSS, and Open Targets
- grounded explanation and extraction with Gemma
- a config-first setup so a new disease can reuse the same workflow
- local-first deployment with optional cloud backends

## What It Solves

Disease knowledge is fragmented across papers, trials, advocacy sites, and scattered updates. Most people who care about a disease do not have a usable research workspace.

This project is meant to help:
- learners get oriented faster
- families and advocates understand the research landscape
- small research teams monitor evidence without custom infrastructure
- builders launch a disease-specific research hub from one codebase

## Why Gemma

Gemma is not the database. It is the portable reasoning layer around the data pipeline.

Gemma helps with:
- paper summarization
- structured extraction
- grounded question answering
- plain-language explanation
- multilingual access

That matters because the same system should run:
- on a local laptop
- on a desktop GPU
- on Ollama-backed home infrastructure
- in Kaggle notebooks
- with cloud fallback when needed

## Current Status

M1 foundation in this repo includes:
- `config.yaml` schema
- `config_loader.py` with defaults and validation
- `src/data_fetcher.py` reading disease-specific values from config
- `src/llm.py` with provider support for `ollama`, `openai`, `anthropic`, and `nim`
- `examples/configs/huntington.yaml` as the HD reference config

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy the Huntington example config or edit `config.yaml` directly:

```bash
cp examples/configs/huntington.yaml config.yaml
```

3. Fetch disease data:

```bash
python3 src/data_fetcher.py
```

## Config Contract

Minimum required fields:
- `disease.name`
- `disease.short_name`
- `disease.mondo_id`
- `search.pubmed_query`
- at least one `targets[]` entry

The loader also validates LLM provider settings so broken cloud/local configurations fail fast instead of failing mid-run.

## Device Story

Use the same repo at different compute tiers:
- `starter`: laptop + Ollama for lightweight chat, summaries, and small fetch runs
- `standard`: desktop GPU for larger corpora and richer extraction
- `always-on`: Jetson or home server for scheduled gathering
- `hosted`: cloud-backed demo for instant public access

The point is not one perfect deployment. The point is that the same disease workspace can run on the hardware people already have.

## Direction

This template is being built to support:
- disease-specific public hubs
- a hosted multi-disease experience
- local/self-hosted deployments for researchers, nonprofits, and advocates

HD is the proof point. The template is the product.
