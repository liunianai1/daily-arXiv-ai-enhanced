#!/usr/bin/env python3
"""
按 submittedDate 从 export.arxiv.org 补爬某一天的论文元数据。
用于 /new 页面爬取失败、或 GitHub Actions cron 漏跑导致缺失的日期。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Iterable, List, Set

import arxiv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill arXiv papers by UTC date")
    parser.add_argument("--date", required=True, help="UTC date YYYY-MM-DD")
    parser.add_argument(
        "--output",
        default=None,
        help="Output jsonl path (default: ../data/{date}.jsonl)",
    )
    parser.add_argument(
        "--categories",
        default=os.environ.get("CATEGORIES", "cs.CV, cs.CL"),
        help="Comma-separated arXiv categories",
    )
    return parser.parse_args()


def day_window(date_str: str) -> tuple[str, str]:
    day = datetime.strptime(date_str, "%Y-%m-%d")
    start = day.strftime("%Y%m%d0000")
    end = day.strftime("%Y%m%d2359")
    return start, end


def fetch_day(date_str: str, categories: Iterable[str]) -> List[dict]:
    cats = [c.strip() for c in categories if c.strip()]
    if not cats:
        raise SystemExit("No categories configured")

    start, end = day_window(date_str)
    cat_q = " OR ".join(f"cat:{c}" for c in cats)
    query = f"submittedDate:[{start} TO {end}] AND ({cat_q})"
    print(f"Query: {query}", file=sys.stderr)

    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=5)
    search = arxiv.Search(
        query=query,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
        max_results=2000,
    )

    seen: Set[str] = set()
    papers: List[dict] = []
    for paper in client.results(search):
        pid = paper.get_short_id()
        # strip version suffix for stable id (2609.12345v1 -> 2609.12345)
        base_id = pid.rsplit("v", 1)[0] if "v" in pid.split(".")[-1] else pid
        if base_id in seen:
            continue
        seen.add(base_id)
        papers.append(
            {
                "id": base_id,
                "categories": list(paper.categories),
                "pdf": f"https://arxiv.org/pdf/{base_id}",
                "abs": f"https://arxiv.org/abs/{base_id}",
                "authors": [a.name for a in paper.authors],
                "title": paper.title,
                "comment": paper.comment,
                "summary": paper.summary,
            }
        )
        if len(papers) % 25 == 0:
            print(f"Fetched {len(papers)}...", file=sys.stderr)
            time.sleep(1)

    return papers


def main() -> None:
    args = parse_args()
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError as e:
        raise SystemExit(f"Invalid --date: {e}") from e

    out = args.output or os.path.join(
        os.path.dirname(__file__), "..", "data", f"{args.date}.jsonl"
    )
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    papers = fetch_day(args.date, args.categories.split(","))
    print(f"Total unique papers: {len(papers)}", file=sys.stderr)
    if not papers:
        raise SystemExit(f"No papers found for {args.date}")

    with open(out, "w", encoding="utf-8") as f:
        for paper in papers:
            f.write(json.dumps(paper, ensure_ascii=False) + "\n")
    print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
