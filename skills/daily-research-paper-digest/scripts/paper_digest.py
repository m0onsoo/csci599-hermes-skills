#!/usr/bin/env python3
"""Standalone keyless arXiv selector and delivery-history recorder.

This script intentionally uses only the Python standard library so a fresh Hermes
skill installation can run it without installing packages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


ATOM = {"a": "http://www.w3.org/2005/Atom"}
ARXIV_ID = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})$", re.I)
SECRET_LIKE = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}|PRIVATE KEY)", re.I)
STOPWORDS = {"and", "or", "the", "for", "with", "from", "into", "using", "about", "research", "study"}


def fail(message: str) -> None:
    raise SystemExit(f"paper-digest: {message}")


def topic(value: str) -> str:
    result = " ".join(str(value or "").split())
    if not 3 <= len(result) <= 200:
        fail("topic must be 3-200 characters")
    if SECRET_LIKE.search(result):
        fail("topic appears to contain a credential")
    return result


def canonical_id(value: str) -> str:
    result = re.sub(r"v\d+$", "", value.rsplit("/abs/", 1)[-1].strip(), flags=re.I)
    if not ARXIV_ID.fullmatch(result):
        fail("invalid arXiv identifier")
    return result


def search_query(value: str) -> str:
    terms = [
        token_value
        for token_value in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)
        if token_value.lower() not in STOPWORDS and len(token_value) >= 3
    ]
    return " AND ".join(f"all:{item}" for item in terms[:3]) if terms else f'all:"{value}"'


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "deliveries": []}
    except (OSError, json.JSONDecodeError):
        fail("history is unreadable")
    if not isinstance(value, dict) or not isinstance(value.get("deliveries", []), list):
        fail("history has an invalid structure")
    return value


def atom_text(entry: ET.Element, path: str) -> str:
    node = entry.find(path, ATOM)
    return " ".join((node.text if node is not None and node.text else "").split())


def select(args: argparse.Namespace) -> None:
    clean_topic = topic(args.topic)
    state = Path(args.state).expanduser().resolve()
    seen = {str(item.get("arxiv_id")) for item in load(state).get("deliveries", []) if isinstance(item, dict)}
    query = urllib.parse.urlencode(
        {
            "search_query": search_query(clean_topic),
            "start": 0,
            "max_results": 10,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    request = urllib.request.Request(
        f"https://export.arxiv.org/api/query?{query}",
        headers={"Accept": "application/atom+xml", "User-Agent": "CSCI599-A3-paper-digest/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            root = ET.fromstring(response.read(2_000_000))
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError) as exc:
        fail(f"arXiv query failed ({type(exc).__name__})")
    for entry in root.findall("a:entry", ATOM):
        identifier = canonical_id(atom_text(entry, "a:id"))
        if identifier in seen:
            continue
        title = atom_text(entry, "a:title")[:500]
        abstract = atom_text(entry, "a:summary")[:10_000]
        published = atom_text(entry, "a:published")
        if not title or not abstract or not published:
            continue
        payload = {
            "arxiv_id": identifier,
            "title": title,
            "authors": [
                " ".join(node.findtext("a:name", default="", namespaces=ATOM).split())[:200]
                for node in entry.findall("a:author", ATOM)
                if node.findtext("a:name", default="", namespaces=ATOM).strip()
            ][:20],
            "published": published,
            "categories": [node.get("term") for node in entry.findall("a:category", ATOM) if node.get("term")][:20],
            "url": f"https://arxiv.org/abs/{identifier}",
            "abstract": abstract,
            "source": "arXiv Atom API",
            "trust": "untrusted_external_data",
            "topic": clean_topic,
        }
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return
    fail("no undelivered arXiv paper matched the topic")


def record(args: argparse.Namespace) -> None:
    clean_topic = topic(args.topic)
    identifier = canonical_id(args.arxiv_id)
    expected = f"https://arxiv.org/abs/{identifier}"
    if args.url != expected:
        fail("URL is not the canonical arXiv abstract URL")
    title_value = " ".join(args.title.split())[:500]
    if not title_value:
        fail("title is required")
    state = Path(args.state).expanduser().resolve()
    data = load(state)
    deliveries = data.setdefault("deliveries", [])
    if not any(isinstance(item, dict) and item.get("arxiv_id") == identifier for item in deliveries):
        deliveries.append(
            {
                "arxiv_id": identifier,
                "title": title_value,
                "url": expected,
                "topic": clean_topic,
                "delivered_at": datetime.now(UTC).isoformat(),
            }
        )
    data["deliveries"] = deliveries[-365:]
    state.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(state.parent, 0o700)
    with NamedTemporaryFile("w", encoding="utf-8", dir=state.parent, prefix=".history-", delete=False) as stream:
        json.dump(data, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")
        temp = Path(stream.name)
    os.chmod(temp, 0o600)
    temp.replace(state)
    print(json.dumps({"recorded": identifier, "history_size": len(data["deliveries"])}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Select and deduplicate a daily arXiv paper")
    sub = result.add_subparsers(dest="command", required=True)
    choose = sub.add_parser("select")
    choose.add_argument("--topic", required=True)
    choose.add_argument("--state", required=True)
    choose.set_defaults(run=select)
    save = sub.add_parser("record")
    save.add_argument("--topic", required=True)
    save.add_argument("--arxiv-id", required=True)
    save.add_argument("--title", required=True)
    save.add_argument("--url", required=True)
    save.add_argument("--state", required=True)
    save.set_defaults(run=record)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.run(arguments)
