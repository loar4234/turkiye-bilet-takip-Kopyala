
import os
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from html import unescape


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

BILETNERDE_URL = "https://biletnerde.com/etkinlikler"
TFF_URL = "https://www.tff.org/default.aspx?pageID=198"
PASSO_EVENT_URL = "https://ssrprod.passo.com.tr/en/"
PASSO_SUPERLIG_URL = "https://ssrprod.passo.com.tr/en/category/football-match-ticket/turkish-football-league-tff-super-league-football-tickets/4615/8617"

TR_TZ = timezone(timedelta(hours=3))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml"
}

MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2,
    "mart": 3, "nisan": 4, "mayıs": 5,
    "mayis": 5, "haziran": 6, "temmuz": 7,
    "ağustos": 8, "agustos": 8, "eylül": 9,
    "eylul": 9, "ekim": 10, "kasım": 11,
    "kasim": 11, "aralık": 12, "aralik": 12
}

CITIES = [
    "İstanbul", "Istanbul", "Ankara", "İzmir", "Izmir",
    "Antalya", "Adana", "Bursa", "Eskişehir", "Eskisehir",
    "Trabzon", "Samsun", "Konya", "Gaziantep", "Kayseri",
    "Mersin", "Diyarbakır", "Diyarbakir", "Şanlıurfa",
    "Sanliurfa", "Denizli", "Balıkesir", "Balikesir",
    "Kocaeli", "Muğla", "Mugla", "Aydın", "Aydin",
    "Çanakkale", "Canakkale", "Bolu", "Sakarya",
    "Tekirdağ", "Tekirdag", "Malatya", "Erzurum"
]


def fetch_html(url):
    request = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        html = raw.decode(charset, errors="replace")

        print("HTTP:", response.status, "|", url)
        print("İndirilen veri:", len(raw), "byte")

        return html


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            self.current = {
                "href": attrs.get("href", ""),
                "text": ""
            }

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += " " + data

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.anchors.append(self.current)
            self.current = None


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip()


def parse_event_date(text):
    pattern = (
        r"(\d{1,2})\s*(?:-\s*\d{1,2}\s*)?"
        r"(Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|"
        r"Haziran|Temmuz|Ağustos|Agustos|Eylül|Eylul|"
        r"Ekim|Kasım|Kasim|Aralık|Aralik)"
        r"\s+(\d{4})"
        r"(?:\s*[-–]\s*(\d{1,2}):(\d{2}))?"
    )

    match = re.search(pattern, text, re.IGNORECASE)

    if not match:
        return None

    day = int(match.group(1))
    month = MONTHS.get(match.group(2).lower())
    year = int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)

    if not month:
        return None

    try:
        return datetime(
            year, month, day, hour, minute,
            tzinfo=TR_TZ
        ).isoformat()
    except ValueError:
        return None


def parse_prices(text):
    values = re.findall(r"₺\s*([\d.,]+)", text)
    numbers = []

    for value in values:
        try:
            numbers.append(
                float(value.replace(".", "").replace(",", "."))
            )
        except ValueError:
            pass

    if not numbers:
        return None, None

    return min(numbers), max(numbers)


def find_city(text):
    for city in CITIES:
        if city.lower() in text.lower():
            return city
    return None


def classify_event(text):
    lower = text.lower()

    if "festival" in lower or "festivali" in lower:
        return "festival"

    if any(x in lower for x in [
        "maç", "mac", "futbol", "football", "basketbol"
    ]):
        return "football"

    if any(x in lower for x in [
        "konser", "müzik", "muzik", "symphony"
    ]):
        return "concert"

    return "event"


def normalize_key(value):
    value = unescape(value or "").lower()
    value = value.replace("ı", "i").replace("ş", "s").replace("ğ", "g")
    value = value.replace("ü", "u").replace("ö", "o").replace("ç", "c")
    value = re.sub(r"^one\s+cikan\s+", "", value)
    # Liste kartlarındaki reklam/sponsor önekleri etkinlik kimliği değildir.
    value = re.sub(r"^(?:%?\s*100\s+)?(?:metal|muzik)\s+sunar\s+", "", value)
    value = re.sub(r"^one\s+cikan\s+", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return clean_text(value)


def dedupe_events(events, source):
    # Aynı etkinliğin farklı kart/URL başlıklarını tek kayda indir.
    # Aynı sanatçının farklı günlerdeki konserleri ayrı kalır.
    unique = {}
    for event in events:
        date_part = (event.get("event_date") or "")[:10]
        title_key = normalize_key(event.get("title"))
        city_key = normalize_key(event.get("city"))
        # Başlık sonunda tekrar edilen şehir adını kaldır.
        if city_key and title_key.endswith(" " + city_key):
            title_key = title_key[:-(len(city_key) + 1)]
        key = (title_key, city_key, date_part, event.get("category"))
        if key not in unique:
            # Başlığın biri diğerinin kısaltılmış hali ise aynı gün/şehirde birleştir.
            duplicate_key = None
            new_words = set(title_key.split())
            for old_key in unique:
                old_title, old_city, old_date, old_category = old_key
                old_words = set(old_title.split())
                if (old_city == city_key and old_date == date_part
                    and old_category == event.get("category")
                    and min(len(new_words), len(old_words)) >= 2
                    and (new_words.issubset(old_words) or old_words.issubset(new_words))):
                    duplicate_key = old_key
                    break
            if duplicate_key is None:
                unique[key] = event
                continue
            key = duplicate_key
        current = unique[key]
        # Bilgisi daha dolu kaydı koru; URL ve kaynak kimliği kaybolmasın.
        score_new = sum(event.get(k) not in (None, "", "unknown") for k in
                        ("event_date", "city", "venue", "price_min", "price_max"))
        score_old = sum(current.get(k) not in (None, "", "unknown") for k in
                        ("event_date", "city", "venue", "price_min", "price_max"))
        if score_new > score_old:
            unique[key] = event
    result = list(unique.values())
    removed = len(events) - len(result)
    if removed:
        print(f"[{source}] Aynı etkinliğin {removed} mükerrer kaydı ayıklandı.")
    return result


def classify_music_event(title, text):
    combined = normalize_key(title + " " + text)
    # Açıkça konser olmayan etkinlikleri sanatçı adı içeriyor diye konser sayma.
    non_music = (
        "tiyatro", "theatre", "theater", "stand up", "still standing",
        "comedy", "komedi", "bale", "ballet", "film", "sinema",
        "workshop", "atolye", "konferans", "conference", "sergi",
        "exhibition", "muze", "museum", "cocuk etkinligi", "kids event",
        "futbol", "football", "basketball", "mac bileti", "karaoke",
        "dans gecesi", "dance night", "dj party", "club night",
        "talk show", "soylesi", "sohbet", "standup"
    )
    if any(word in combined for word in non_music):
        return "other"
    if "festival" in combined or "festivali" in combined:
        return "festival"
    if any(word in combined for word in ("mac", "futbol", "football", "basketball")):
        return "football"
    if any(word in combined for word in (
        "konser", "concert", "music", "muzik", "symphony", "live performance",
        "jazz", "caz", "metal", "orchestra", "tour"
    )):
        return "concert"
    # Artist-only event cards on music-category listings are concerts.
    return "concert"


def is_target_biletnerde_event(title, text):
    category = classify_music_event(title, text)
    return category in ("concert", "festival")


def scrape_biletnerde():
    print("\n--- BİLETNERDE TARAMASI (KONSER/FESTİVAL) ---")
    html = fetch_html(BILETNERDE_URL)
    parser = AnchorParser()
    parser.feed(html)
    events = []
    seen = set()

    for anchor in parser.anchors:
        href = anchor["href"]
        text = clean_text(anchor["text"])
        if "/etkinlik/" not in href or len(text) < 8:
            continue
        full_url = urllib.parse.urljoin(BILETNERDE_URL, href)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(full_url).query)
        source_id = query.get("eid", [None])[0] or urllib.parse.urlparse(full_url).path
        if source_id in seen:
            continue

        title = re.sub(
            r"\d{1,2}\s*(?:-\s*\d{1,2}\s*)?(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)\s+\d{4}.*$",
            "", text, flags=re.IGNORECASE
        )
        title = clean_text(re.sub(r"₺\s*[\d.,]+.*$", "", title))
        if not title:
            title = text[:200]

        category = classify_music_event(title, text)
        # Kullanıcının kapsamı konser ve festival; açıkça başka türde olanları alma.
        if category not in ("concert", "festival"):
            continue

        seen.add(source_id)
        event_date = parse_event_date(text)
        price_min, price_max = parse_prices(text)
        events.append({
            "source": "BiletNerde",
            "source_event_id": str(source_id),
            "title": title[:500],
            "category": category,
            "city": find_city(text),
            "venue": None,
            "event_date": event_date,
            "ticket_url": full_url,
            "ticket_status": "unknown",
            "price_min": price_min,
            "price_max": price_max,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

    events = dedupe_events(events, "BiletNerde")
    print("BiletNerde konser/festival bulunan:", len(events))
    for event in events[:8]:
        print("ETKİNLİK:", event["title"], "|", event["category"], "|", event["city"], "|", event["event_date"])
    return events

def scrape_tff():
    print("\n--- TFF SÜPER LİG TARAMASI ---")

    html = fetch_html(TFF_URL)

    parser = TextParser()
    parser.feed(html)

    full_text = clean_text(" ".join(parser.parts))

    pattern = re.compile(
        r"(\d{2}\.\d{2}\.\d{4})\s+"
        r"(\d{1,2}:\d{2})\s+"
        r"([A-ZÇĞİÖŞÜ0-9 .()&/]+?)"
        r"\s+-\s+"
        r"([A-ZÇĞİÖŞÜ0-9 .()&/]+?)"
        r"(?=\s+Detaylar|\s+\d{2}\.\d{2}\.\d{4}|$)"
    )

    matches = pattern.findall(full_text)

    events = []
    seen = set()

    for date_text, time_text, home, away in matches:
        # Takım isimlerine müdahale etmiyoruz.
        home = clean_text(home)
        away = clean_text(away)

        if len(home) < 3 or len(away) < 3:
            continue

        try:
            date_value = datetime.strptime(
                date_text + " " + time_text,
                "%d.%m.%Y %H:%M"
            ).replace(tzinfo=TR_TZ)
        except ValueError:
            continue

        title = f"{home} - {away}"

        source_id = (
            date_value.strftime("%Y%m%d%H%M")
            + "-"
            + home
            + "-"
            + away
        )

        if source_id in seen:
            continue

        seen.add(source_id)

        events.append({
            "source": "TFF",
            "source_event_id": source_id[:250],
            "title": title[:500],
            "category": "football",
            "city": None,
            "venue": None,
            "event_date": date_value.isoformat(),
            "ticket_url": TFF_URL,
            "ticket_status": "unknown",
            "price_min": None,
            "price_max": None,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

    print("TFF bulunan maç:", len(events))

    for event in events:
        print("MAÇ:", event["title"], "|", event["event_date"])

    return events



def parse_passo_date(text):
    # Önce etkinliğin yazıyla belirtilen tarihini bul. Sayısal tarihler
    # çoğu zaman öncelikli satış başlangıcıdır; etkinlik tarihi değildir.
    months = {
        "january": 1, "jan": 1, "ocak": 1,
        "february": 2, "feb": 2, "şubat": 2, "subat": 2,
        "march": 3, "mar": 3, "mart": 3,
        "april": 4, "apr": 4, "nisan": 4,
        "may": 5, "mayıs": 5, "mayis": 5,
        "june": 6, "jun": 6, "haziran": 6,
        "july": 7, "jul": 7, "temmuz": 7,
        "august": 8, "aug": 8, "ağustos": 8, "agustos": 8,
        "september": 9, "sep": 9, "eylül": 9, "eylul": 9,
        "october": 10, "oct": 10, "ekim": 10,
        "november": 11, "nov": 11, "kasım": 11, "kasim": 11,
        "december": 12, "dec": 12, "aralık": 12, "aralik": 12
    }
    month_pattern = "|".join(sorted(months, key=len, reverse=True))
    m = re.search(
        rf"(\d{1,2})\s+({month_pattern})\s+(\d{4})(?:[^\d]{{0,35}}(\d{1,2}):(\d{2}))?",
        text, re.IGNORECASE
    )
    if m:
        month = months.get(m.group(2).lower())
        try:
            return datetime(
                int(m.group(3)), month, int(m.group(1)),
                int(m.group(4) or 0), int(m.group(5) or 0),
                tzinfo=TR_TZ
            ).isoformat()
        except (ValueError, TypeError):
            pass

    # Türkçe PASSO detaylarında "21 Kasım 2026 Saat: 19:00" formatı.
    m = re.search(
        r"(\d{1,2})\s+(" + month_pattern + r")\s+(\d{4})\s*(?:Saat:?\s*)?(\d{1,2}):(\d{2})",
        text, re.IGNORECASE
    )
    if m:
        month = months.get(m.group(2).lower())
        try:
            return datetime(
                int(m.group(3)), month, int(m.group(1)),
                int(m.group(4)), int(m.group(5)), tzinfo=TR_TZ
            ).isoformat()
        except (ValueError, TypeError):
            pass

    # Sayısal biçimi yalnızca metin tarih biçimi bulunamadığında kullan.
    m = re.search(r"(\d{1,2})[./ -]+(\d{1,2})[./ -]+(\d{4})\s*(?:Saat:?\s*)?(\d{1,2}):(\d{2})", text, re.IGNORECASE)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                            int(m.group(4)), int(m.group(5)), tzinfo=TR_TZ).isoformat()
        except ValueError:
            pass
    return None


def passo_ticket_status(text):
    lower = unescape(text).lower()
    sold_phrases = [
        "biletler tükendi", "biletler tükenmiştir", "sold out", "all tickets are sold",
        "no tickets available", "event is sold out", "currently unavailable"
    ]
    not_started_phrases = [
        "satış henüz başlamadı", "satışa henüz açılmadı",
        "not yet on sale", "sales have not started", "coming soon"
    ]
    if any(phrase in lower for phrase in sold_phrases):
        return "sold_out"
    if any(phrase in lower for phrase in not_started_phrases):
        return "not_on_sale"

    buy_phrases = [
        "buy ticket", "buy tickets", "buy now", "bilet al",
        "hemen al", "tickets available", "select ticket", "ticket selection"
    ]
    has_price = bool(re.search(r"(?:₺|try)\s*[\d.,]+|[\d.,]+\s*(?:₺|try)", lower))
    # Genel "sales" kelimesi tek başına satışta kanıtı değildir.
    if any(phrase in lower for phrase in buy_phrases) and has_price:
        return "on_sale"
    return "unknown"

def passo_metadata_title(html):
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r'<title[^>]*>(.*?)</title>'
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = clean_text(unescape(match.group(1)))
            value = re.sub(r"\s*[|–-]\s*PASSO.*$", "", value, flags=re.IGNORECASE)
            if len(value) > 3 and "share:" not in value.lower():
                return value
    return None


def extract_passo_event_links(html, listing_url, listing_type):
    parser = AnchorParser()
    parser.feed(html)
    found = {}
    for anchor in parser.anchors:
        href = anchor.get("href", "")
        if "/event/" not in href:
            continue
        full_url = urllib.parse.urljoin(listing_url, href)
        path = urllib.parse.urlparse(full_url).path.rstrip("/")
        source_id = path.split("/")[-1]
        if not source_id.isdigit():
            continue
        title = clean_text(anchor.get("text", ""))
        if len(title) < 3:
            continue
        category = "football" if listing_type == "football" else None
        found[source_id] = {"url": full_url, "title": title, "category": category}

    # SSR/Next.js sayfalarında bazı etkinlikler bağlantı yerine gömülü JSON içinde bulunabiliyor.
    # Yalnızca gerçek /event/<slug>/<numeric-id> desenlerini al; rastgele sayıları etkinlik sanma.
    for match in re.finditer(r"[\"']([^\"']*/event/[^\"']*/(\d{5,})[^\"']*)[\"']", html, re.IGNORECASE):
        raw_url, source_id = match.group(1), match.group(2)
        full_url = urllib.parse.urljoin(listing_url, unescape(raw_url).replace("\\/", "/"))
        if source_id not in found:
            found[source_id] = {
                "url": full_url,
                "title": "",
                "category": "football" if listing_type == "football" else None
            }
    return found


def scrape_passo():
    print("\n--- PASSO TARAMASI (KONSER/FESTİVAL + SÜPER LİG) ---")
    discovered = {}

    # Ana sayfanın yanı sıra PASSO'nun kendi konser/festival kategori sayfalarını da tara.
    listing_pages = [
        ("concert_event", PASSO_EVENT_URL),
        ("football", PASSO_SUPERLIG_URL)
    ]

    try:
        home_html = fetch_html(PASSO_EVENT_URL)
        home_parser = AnchorParser()
        home_parser.feed(home_html)
        category_seen = {PASSO_EVENT_URL, PASSO_SUPERLIG_URL}
        category_keywords = (
            "concert", "music", "festival", "konser", "muzik",
            "müzik", "metal", "jazz", "caz"
        )
        for anchor in home_parser.anchors:
            href = anchor.get("href", "")
            label = clean_text(anchor.get("text", "")).lower()
            if "/category/" not in href:
                continue
            if not any(word in label for word in category_keywords):
                continue
            category_url = urllib.parse.urljoin(PASSO_EVENT_URL, href)
            if category_url not in category_seen:
                category_seen.add(category_url)
                listing_pages.append(("concert_event", category_url))
            if len(listing_pages) >= 14:
                break
        print("[PASSO] Ek konser/festival kategori sayfası:", max(0, len(listing_pages) - 2))
    except Exception as error:
        print("[UYARI] PASSO kategori keşfi yapılamadı:", error)

    checked_pages = set()
    for listing_type, listing_url in listing_pages:
        if listing_url in checked_pages:
            continue
        checked_pages.add(listing_url)
        try:
            html = home_html if listing_url == PASSO_EVENT_URL and "home_html" in locals() else fetch_html(listing_url)
            page_events = extract_passo_event_links(html, listing_url, listing_type)
            print(f"[PASSO] {listing_type}: {len(page_events)} etkinlik bağlantısı bulundu | {listing_url}")
            for source_id, item in page_events.items():
                if listing_type == "football":
                    discovered[source_id] = item
                else:
                    discovered.setdefault(source_id, item)
        except Exception as error:
            print(f"[UYARI] PASSO liste sayfası okunamadı ({listing_type}):", error)

    events = []
    for source_id, item in discovered.items():
        try:
            detail_html = fetch_html(item["url"])
            parser = TextParser()
            parser.feed(detail_html)
            detail_text = clean_text(" ".join(parser.parts))
            title = passo_metadata_title(detail_html) or item.get("title") or ""

            heading_match = re.search(
                r"TICKET DETAILS\s+(.+?)\s+(?:\d{1,2}\s+\w+|Sales|Ticket Information)",
                detail_text, re.IGNORECASE
            )
            if heading_match and (not title or "share:" in title.lower()):
                title = clean_text(heading_match.group(1))

            if not title or "share:" in title.lower():
                title = clean_text(item.get("title", "")) or f"PASSO etkinliği {source_id}"

            category = item["category"]
            if category is None:
                category = classify_music_event(title, detail_text[:2500])
                if category not in ("concert", "festival"):
                    # PASSO genel liste sayfasındaki spor/diğer etkinlikleri kapsam dışında tut.
                    continue

            price_min, price_max = parse_prices(detail_text)
            status = passo_ticket_status(detail_html + " " + detail_text)
            event_date = parse_passo_date(detail_text)

            events.append({
                "source": "PASSO",
                "source_event_id": str(source_id),
                "title": title[:500],
                "category": category,
                "city": find_city(detail_text),
                "venue": None,
                "event_date": event_date,
                "ticket_url": item["url"],
                "ticket_status": status,
                "price_min": price_min,
                "price_max": price_max,
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception as error:
            print(f"[UYARI] PASSO etkinlik detayı okunamadı ({source_id}):", error)

    events = dedupe_events(events, "PASSO")
    counts = {}
    for event in events:
        counts[event["ticket_status"]] = counts.get(event["ticket_status"], 0) + 1
    print("PASSO bulunan etkinlik/maç:", len(events), "| Durum dağılımı:", counts)
    for event in events[:20]:
        print("PASSO:", event["title"], "|", event["category"], "|", event["ticket_status"], "|", event["event_date"])
    return events

def supabase_request(endpoint, method="GET", data=None, prefer=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    if prefer:
        headers["Prefer"] = prefer

    body = None

    if data is not None:
        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(request, timeout=40) as response:
        result = response.read().decode("utf-8", errors="replace")
        return response.status, result



def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[UYARI] Telegram Secrets eksik; bildirim gönderilmedi.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("ok"):
                print("[TELEGRAM] Bildirim gönderildi.")
                return True
            print("[TELEGRAM HATA]", result)
    except Exception as error:
        print("[TELEGRAM HATA]", error)

    return False


def numeric_value(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TR_TZ)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    except (TypeError, ValueError):
        return value


def find_event_changes(events):
    changes = []

    by_source = {}
    for event in events:
        by_source.setdefault(event["source"], []).append(event)

    for source, source_events in by_source.items():
        endpoint = (
            SUPABASE_URL
            + "/rest/v1/events?"
            + urllib.parse.urlencode({
                "select": "source_event_id,title,event_date,price_min,price_max,ticket_status",
                "source": f"eq.{source}"
            })
        )

        try:
            _, result = supabase_request(endpoint, method="GET")
            existing_rows = json.loads(result or "[]")
            existing = {
                str(row.get("source_event_id")): row
                for row in existing_rows
            }
        except Exception as error:
            print(f"[UYARI] {source} eski kayıtları okunamadı; bildirim kontrolü atlandı:", error)
            continue

        for event in source_events:
            old = existing.get(str(event["source_event_id"]))

            if old is None:
                changes.append(("new", event, []))
                continue

            changed_fields = []

            if normalized_datetime(old.get("event_date")) != normalized_datetime(event.get("event_date")):
                changed_fields.append("tarih/saat")

            if numeric_value(old.get("price_min")) != numeric_value(event.get("price_min")):
                changed_fields.append("en düşük fiyat")

            if numeric_value(old.get("price_max")) != numeric_value(event.get("price_max")):
                changed_fields.append("en yüksek fiyat")

            old_status = old.get("ticket_status") or "unknown"
            new_status = event.get("ticket_status") or "unknown"
            if new_status != "unknown" and old_status != new_status:
                changed_fields.append("bilet durumu: " + old_status + " → " + new_status)

            if changed_fields:
                changes.append(("updated", event, changed_fields))

    return changes


def notify_event_changes(changes):
    for change_type, event, fields in changes:
        if change_type == "new":
            heading = "🆕 YENİ ETKİNLİK / MAÇ"
        else:
            heading = "🔔 ETKİNLİK BİLGİSİ DEĞİŞTİ: " + ", ".join(fields)

        category = {
            "football": "Süper Lig maçı",
            "concert": "Konser",
            "festival": "Festival",
            "event": "Etkinlik"
        }.get(event.get("category"), "Etkinlik")

        date_text = event.get("event_date") or "Tarih belirtilmemiş"
        if date_text != "Tarih belirtilmemiş":
            try:
                date_text = datetime.fromisoformat(date_text).strftime("%d.%m.%Y %H:%M")
            except ValueError:
                pass

        lines = [
            heading,
            f"Tür: {category}",
            f"Adı: {event.get('title') or 'Bilinmiyor'}",
            f"Tarih: {date_text}"
        ]

        status_labels = {
            "on_sale": "Satışta",
            "sold_out": "Tükendi",
            "not_on_sale": "Henüz satışta değil",
            "unknown": "Doğrulanamadı"
        }
        lines.append("Bilet durumu: " + status_labels.get(event.get("ticket_status"), "Doğrulanamadı"))

        if event.get("city"):
            lines.append(f"Şehir: {event['city']}")

        low = event.get("price_min")
        high = event.get("price_max")
        if low is not None or high is not None:
            if low is not None and high is not None and low != high:
                lines.append(f"Fiyat: {low} - {high} TL")
            else:
                lines.append(f"Fiyat: {low if low is not None else high} TL")

        if event.get("ticket_url"):
            lines.append(f"Bilet bağlantısı: {event['ticket_url']}")

        telegram_send("\n".join(lines))


def merge_existing_data(events):
    grouped = {}
    for event in events:
        grouped.setdefault(event["source"], []).append(event)
    for source, source_events in grouped.items():
        endpoint = (SUPABASE_URL + "/rest/v1/events?" +
                    urllib.parse.urlencode({
                        "select": "source_event_id,event_date,price_min,price_max,ticket_status,city,venue",
                        "source": f"eq.{source}"
                    }))
        try:
            _, raw = supabase_request(endpoint, method="GET")
            rows = json.loads(raw or "[]")
            existing = {str(row.get("source_event_id")): row for row in rows}
        except Exception as error:
            print(f"[UYARI] {source} eski veriler birleştirilemedi:", error)
            continue
        for event in source_events:
            old = existing.get(str(event["source_event_id"]))
            if not old:
                continue
            for field in ("event_date", "price_min", "price_max", "city", "venue"):
                if event.get(field) in (None, "") and old.get(field) not in (None, ""):
                    event[field] = old[field]
            if event.get("ticket_status") in (None, "", "unknown") and old.get("ticket_status") not in (None, "", "unknown"):
                event["ticket_status"] = old["ticket_status"]
    return events


def save_and_notify(events):
    if not events:
        return

    # Kaynakta bilgi geçici olarak eksikse, DB'deki doğrulanmış veriyi
    # unknown/None ile ezme. Bu özellikle stok durumu bildirimlerini korur.
    events = merge_existing_data(events)
    changes = find_event_changes(events)
    save_events(events)

    if changes:
        print("Telegram bildirimi gereken değişiklik:", len(changes))
        notify_event_changes(changes)
    else:
        print("Yeni etkinlik veya fiyat/tarih değişikliği yok.")



def save_events(events):
    if not events:
        print("Kaydedilecek etkinlik yok.")
        return

    endpoint = (
        SUPABASE_URL
        + "/rest/v1/events"
        + "?on_conflict=source,source_event_id"
    )

    for start in range(0, len(events), 100):
        batch = events[start:start + 100]

        status, _ = supabase_request(
            endpoint,
            method="POST",
            data=batch,
            prefer="resolution=merge-duplicates,return=minimal"
        )

        print(
            "Supabase etkinlik kaydı:",
            len(batch),
            "| HTTP:",
            status
        )


def save_source_check(source, status, count, error=None):
    endpoint = SUPABASE_URL + "/rest/v1/source_checks"

    result = {
        "source": source,
        "status": status,
        "events_found": count,
        "error_message": str(error)[:500] if error else None
    }

    status_code, _ = supabase_request(
        endpoint,
        method="POST",
        data=result,
        prefer="return=minimal"
    )

    print("Kaynak kontrol kaydı:", source, status_code)


def run_biletnerde():
    try:
        events = scrape_biletnerde()

        if not events:
            raise RuntimeError("BiletNerde etkinlik ayrıştırılamadı.")

        save_and_notify(events)
        save_source_check("BiletNerde", "success", len(events))

        return events

    except Exception as error:
        print("[HATA] BiletNerde:", error)
        save_source_check("BiletNerde", "error", 0, error)
        return []


def run_passo():
    try:
        events = scrape_passo()
        if not events:
            raise RuntimeError("PASSO sayfalarından etkinlik/maç ayrıştırılamadı.")

        # İlk taramada mevcut PASSO kayıtlarını sessizce başlangıç verisi olarak kaydet;
        # böylece ilk çalıştırmada onlarca eski etkinlik için bildirim yağmuru oluşmaz.
        check_url = (
            SUPABASE_URL + "/rest/v1/events?"
            + urllib.parse.urlencode({
                "select": "source_event_id",
                "source": "eq.PASSO",
                "limit": "1"
            })
        )
        _, existing_result = supabase_request(check_url, method="GET")
        existing_pass = json.loads(existing_result or "[]")

        if existing_pass:
            save_and_notify(events)
        else:
            print("[PASSO] İlk tarama: mevcut etkinlikler başlangıç verisi olarak kaydediliyor; bildirim gönderilmeyecek.")
            save_events(events)

        save_source_check("PASSO", "success", len(events))
        return events
    except Exception as error:
        print("[HATA] PASSO:", error)
        save_source_check("PASSO", "error", 0, error)
        return []


def run_tff():
    try:
        events = scrape_tff()

        if not events:
            raise RuntimeError("TFF maçları ayrıştırılamadı.")

        # Yalnızca bulunan maçları ekle/güncelle; diğer TFF kayıtlarını silme.
        save_and_notify(events)

        save_source_check("TFF", "success", len(events))

        return events

    except Exception as error:
        print("[HATA] TFF:", error)
        save_source_check("TFF", "error", 0, error)
        return []


def main():
    print("=" * 55)
    print("TÜRKİYE BİLET TAKİP - KONSER/FESTİVAL + SÜPER LİG")
    print("Zaman:", datetime.now(timezone.utc).isoformat())
    print("=" * 55)

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase GitHub Secrets eksik!")

    biletnerde_events = run_biletnerde()
    passo_events = run_passo()
    tff_events = run_tff()

    total = len(biletnerde_events) + len(passo_events) + len(tff_events)

    print("\n" + "=" * 55)
    print("TARAMA TAMAMLANDI")
    print("BiletNerde (konser/festival):", len(biletnerde_events))
    print("PASSO:", len(passo_events))
    print("TFF:", len(tff_events))
    print("TOPLAM:", total)
    print("=" * 55)


if __name__ == "__main__":
    main()
