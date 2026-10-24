#!/usr/bin/env python3
"""Fetch the Platform Bind Zotero group library into _data/zotero.json.

Jekyll reads the output as site.data.zotero. Each subcollection page names a
Zotero collection, and its references are the top-level items in it. Notes
attached to an item become its annotation.

Run this before committing, so the pushed site has the latest references.

Usage: python3 scripts/fetch_zotero.py
Set ZOTERO_API_KEY if the library is not public.
"""

import html
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

GROUP_ID = "6730694"
API = f"https://api.zotero.org/groups/{GROUP_ID}"
OUTPUT = Path(__file__).resolve().parent.parent / "_data" / "zotero.json"

CREATOR_ROLES = ["author", "editor", "contributor", "programmer", "presenter"]
SOURCE_FIELDS = [
    "publicationTitle", "proceedingsTitle", "bookTitle", "websiteTitle",
    "blogTitle", "forumTitle", "programTitle", "repository",
]
PUBLISHER_FIELDS = ["institution", "university", "publisher", "company", "label"]


def fetch_all(path):
    """Fetch every result of a paged API request."""
    results = []
    start = 0
    while True:
        url = f"{API}{path}{'&' if '?' in path else '?'}limit=100&start={start}"
        req = urllib.request.Request(url, headers={"Zotero-API-Version": "3"})
        if os.environ.get("ZOTERO_API_KEY"):
            req.add_header("Zotero-API-Key", os.environ["ZOTERO_API_KEY"])
        with urllib.request.urlopen(req, timeout=30) as res:
            page = json.load(res)
            total = int(res.headers.get("Total-Results", len(page)))
        results.extend(page)
        start += len(page)
        if not page or start >= total:
            return results


class NoteCleaner(HTMLParser):
    """Keeps a safe subset of note HTML: paragraphs, emphasis, lists, links."""

    ALLOWED = {"p", "br", "em", "i", "strong", "b", "ul", "ol", "li", "blockquote", "a", "code"}
    HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    DROPPED = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROPPED:
            self.dropping += 1
        elif tag in self.HEADINGS:
            self.out.append("<p><strong>")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if re.match(r"https?://", href):
                self.out.append(f'<a href="{html.escape(href)}">')
            else:
                self.out.append("<a>")
        elif tag in self.ALLOWED:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in self.DROPPED:
            self.dropping = max(0, self.dropping - 1)
        elif tag in self.HEADINGS:
            self.out.append("</strong></p>")
        elif tag in self.ALLOWED and tag != "br":
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(html.escape(data, quote=False))


def clean_note(note_html):
    cleaner = NoteCleaner()
    cleaner.feed(note_html)
    cleaner.close()
    text = "".join(cleaner.out).strip()
    text = re.sub(r"<p>\s*</p>", "", text)
    if text and not text.startswith("<"):
        text = f"<p>{text}</p>"
    return text


def format_name(creator):
    if creator.get("name"):
        return creator["name"]
    last = creator.get("lastName", "")
    initials = " ".join(
        "-".join(part[:1] + "." for part in word.split("-"))
        for word in creator.get("firstName", "").replace(".", " ").split()
    )
    return f"{last}, {initials}" if initials else last


def format_creators(creators):
    for role in CREATOR_ROLES:
        names = [format_name(c) for c in creators if c.get("creatorType") == role]
        if names:
            if len(names) == 1:
                return names[0]
            return ", ".join(names[:-1]) + " & " + names[-1]
    return ""


def format_source(data):
    parts = [next((data[f] for f in SOURCE_FIELDS if data.get(f)), "")]
    if data.get("volume"):
        parts.append(data["volume"] + (f"({data['issue']})" if data.get("issue") else ""))
    parts.append(data.get("pages", ""))
    parts.append(next((data[f] for f in PUBLISHER_FIELDS if data.get(f)), ""))
    return ", ".join(p for p in parts if p)


def to_reference(item, notes):
    data = item["data"]
    doi = data.get("DOI", "")
    return {
        "key": data["key"],
        "type": data["itemType"],
        "title": data.get("title", ""),
        "authors": format_creators(data.get("creators", [])),
        "year": item.get("meta", {}).get("parsedDate", "")[:4],
        "source": format_source(data),
        "url": data.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        "abstract": data.get("abstractNote", ""),
        "annotation": "\n".join(notes),
        "tags": sorted(t["tag"] for t in data.get("tags", [])),
    }


def main():
    collections = fetch_all("/collections")
    items = fetch_all("/items")

    names = {c["key"]: c["data"]["name"] for c in collections}
    notes = {}
    for item in items:
        data = item["data"]
        if data["itemType"] == "note" and data.get("parentItem"):
            cleaned = clean_note(data.get("note", ""))
            if cleaned:
                notes.setdefault(data["parentItem"], []).append(cleaned)

    by_collection = {name: [] for name in names.values()}
    for item in items:
        data = item["data"]
        if data["itemType"] in ("note", "attachment", "annotation") or data.get("deleted"):
            continue
        reference = to_reference(item, notes.get(data["key"], []))
        for key in data.get("collections", []):
            if key in names:
                by_collection[names[key]].append(reference)

    for references in by_collection.values():
        references.sort(key=lambda r: r["title"].lower())
        references.sort(key=lambda r: r["year"], reverse=True)

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"collections": by_collection}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    total = sum(len(r) for r in by_collection.values())
    print(f"Wrote {total} references in {len(by_collection)} collections to {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except OSError as err:
        sys.exit(f"Could not fetch the Zotero library: {err}")
