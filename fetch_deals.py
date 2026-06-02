#!/usr/bin/env python3
"""
Deal Fetcher - Pulls deals from DealNews RSS, Slickdeals RSS, and Reddit r/deals
Filters by category keywords and discount threshold, outputs deals.json
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
import html

# ── Category keyword map ──────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "Electronics & Tech": [
        "tv", "monitor", "laptop", "computer", "tablet", "ipad", "iphone",
        "samsung", "sony", "lg", "cpu", "gpu", "ssd", "hard drive", "router",
        "headphones", "earbuds", "speaker", "camera", "projector", "streaming",
        "nintendo", "playstation", "xbox", "gaming", "keyboard", "mouse",
    ],
    "Tools & Hardware": [
        "drill", "saw", "sander", "compressor", "nailer", "stapler", "wrench",
        "socket", "dewalt", "milwaukee", "makita", "ryobi", "craftsman", "ridgid",
        "metabo", "tool", "hardware", "workbench", "clamp", "level", "bit set",
        "lowe", "home depot", "harbor freight",
    ],
    "Home & Garden": [
        "lawn mower", "leaf blower", "weed", "trimmer", "garden", "hose",
        "fertilizer", "mulch", "planter", "shed", "fence", "deck", "patio",
        "furniture", "grill", "bbq", "smoker", "big green egg", "weber",
        "pressure washer", "vacuum", "air purifier", "humidifier", "dehumidifier",
    ],
    "Outdoor & Lawn": [
        "outdoor", "camping", "hiking", "tent", "sleeping bag", "backpack",
        "kayak", "fishing", "hunting", "atv", "lawn", "tractor", "chainsaw",
        "ego", "greenworks", "husqvarna",
    ],
    "Sporting Goods": [
        "treadmill", "bike", "bicycle", "peloton", "weights", "dumbbell",
        "kettlebell", "gym", "fitness", "yoga", "running", "shoes", "sneakers",
        "nike", "adidas", "under armour", "north face", "columbia",
    ],
    "Clothing & Shoes": [
        "shirt", "pants", "jacket", "coat", "hoodie", "sweater", "dress",
        "shoes", "boots", "sneakers", "sandals", "clothing", "apparel",
        "levi", "gap", "old navy", "h&m", "uniqlo", "nike", "adidas",
    ],
}

PREFERRED_RETAILERS = ["amazon", "walmart", "best buy", "target", "lowe", "home depot", "ace hardware"]
MIN_DISCOUNT = 20  # percent

FEEDS = [
    {
        "name": "Slickdeals",
        "url": "https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1",
        "type": "rss",
    },
    {
        "name": "DealNews",
        "url": "https://www.dealnews.com/c142/Electronics/?rss=1",
        "type": "rss",
        "category_hint": "Electronics & Tech",
    },
    {
        "name": "DealNews Tools",
        "url": "https://www.dealnews.com/c238/Home-Garden/?rss=1",
        "type": "rss",
        "category_hint": "Home & Garden",
    },
]

def fetch_url(url, timeout=15):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (deal-tracker-bot/1.0)"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  [WARN] Failed to fetch {url}: {e}")
        return None

def extract_discount(text):
    """Try to pull a discount % from title/description text."""
    patterns = [
        r'(\d+)%\s*off',
        r'save\s+(\d+)%',
        r'(\d+)%\s*discount',
        r'\$(\d+)\s+off',  # dollar off — treat as unknown %
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if '%' in p or 'off' in p.lower():
                return val
    return None

def detect_category(text):
    text_lower = text.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score:
            scores[cat] = score
    if not scores:
        return "Other"
    return max(scores, key=scores.get)

def detect_retailer(text):
    text_lower = text.lower()
    for r in PREFERRED_RETAILERS:
        if r in text_lower:
            return r.title()
    return "Various"

def parse_rss(content, source_name, category_hint=None):
    deals = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"  [WARN] XML parse error for {source_name}: {e}")
        return deals

    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    items = root.findall(".//item")

    for item in items[:40]:
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")

        title = html.unescape(title_el.text.strip()) if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else "#"
        desc = html.unescape(desc_el.text or "") if desc_el is not None else ""
        # Strip HTML tags from description
        desc_clean = re.sub(r'<[^>]+>', ' ', desc).strip()
        pub = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

        combined = f"{title} {desc_clean}"
        discount = extract_discount(combined)
        category = category_hint or detect_category(combined)
        retailer = detect_retailer(combined)

        # Filter: must be in a desired category and meet discount threshold (or be from preferred retailer)
        in_preferred_cat = category != "Other"
        meets_discount = discount is not None and discount >= MIN_DISCOUNT
        preferred_retailer = any(r in combined.lower() for r in PREFERRED_RETAILERS)

        if not in_preferred_cat:
            continue
        if not (meets_discount or preferred_retailer):
            continue

        # Parse date
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub)
            date_iso = dt.isoformat()
            date_display = dt.strftime("%b %d, %I:%M %p")
        except Exception:
            date_iso = datetime.now(timezone.utc).isoformat()
            date_display = "Recent"

        deals.append({
            "id": f"{source_name}-{abs(hash(link)) % 999999:06d}",
            "title": title,
            "description": desc_clean[:200],
            "link": link,
            "source": source_name,
            "retailer": retailer,
            "category": category,
            "discount": discount,
            "date_iso": date_iso,
            "date_display": date_display,
        })

    return deals

def main():
    all_deals = []
    seen_titles = set()

    for feed in FEEDS:
        print(f"Fetching {feed['name']}...")
        content = fetch_url(feed["url"])
        if not content:
            continue

        deals = parse_rss(content, feed["name"], feed.get("category_hint"))
        print(f"  → {len(deals)} deals matched")

        for d in deals:
            # Deduplicate by normalized title
            norm = re.sub(r'\W+', '', d["title"].lower())[:60]
            if norm not in seen_titles:
                seen_titles.add(norm)
                all_deals.append(d)

    # Sort newest first
    all_deals.sort(key=lambda x: x["date_iso"], reverse=True)

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(all_deals),
        "deals": all_deals,
    }

    with open("deals.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Wrote {len(all_deals)} deals to deals.json")

if __name__ == "__main__":
    main()
