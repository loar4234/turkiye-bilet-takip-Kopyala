
import os
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

BILETNERDE_URL = "https://biletnerde.com/etkinlikler"
TFF_URL = "https://www.tff.org/default.aspx?pageID=198"

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
        "maç", "mac", "futbol", "spor", "basketbol"
    ]):
        return "football"

    if any(x in lower for x in [
        "konser", "müzik", "muzik", "symphony"
    ]):
        return "concert"

    return "event"


def scrape_biletnerde():
    print("\n--- BİLETNERDE TARAMASI ---")

    html = fetch_html(BILETNERDE_URL)

    parser = AnchorParser()
    parser.feed(html)

    events = []
    seen = set()

    for anchor in parser.anchors:
        href = anchor["href"]
        text = clean_text(anchor["text"])

        if "/etkinlik/" not in href:
            continue

        if len(text) < 8:
            continue

        full_url = urllib.parse.urljoin(BILETNERDE_URL, href)

        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(full_url).query
        )

        source_id = (
            query.get("eid", [None])[0]
            or urllib.parse.urlparse(full_url).path
        )

        if source_id in seen:
            continue

        seen.add(source_id)

        event_date = parse_event_date(text)
        price_min, price_max = parse_prices(text)

        title = re.sub(
            r"\d{1,2}\s*(?:-\s*\d{1,2}\s*)?"
            r"(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|"
            r"Haziran|Temmuz|Ağustos|Agustos|Eylül|Eylul|"
            r"Ekim|Kasım|Kasim|Aralık|Aralik)"
            r"\s+\d{4}.*$",
            "",
            text,
            flags=re.IGNORECASE
        )

        title = re.sub(r"₺\s*[\d.,]+.*$", "", title)
        title = clean_text(title)

        if not title:
            title = text[:200]

        events.append({
            "source": "BiletNerde",
            "source_event_id": str(source_id),
            "title": title[:500],
            "category": classify_event(text),
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

    print("BiletNerde bulunan etkinlik:", len(events))

    for event in events[:5]:
        print(
            "ETKİNLİK:",
            event["title"],
            "|",
            event["city"],
            "|",
            event["event_date"]
        )

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

        save_events(events)
        save_source_check("BiletNerde", "success", len(events))

        return events

    except Exception as error:
        print("[HATA] BiletNerde:", error)
        save_source_check("BiletNerde", "error", 0, error)
        return []


def run_tff():
    try:
        events = scrape_tff()

        if not events:
            raise RuntimeError("TFF maçları ayrıştırılamadı.")

        # Yalnızca bulunan maçları ekle/güncelle; diğer TFF kayıtlarını silme.
        save_events(events)

        save_source_check("TFF", "success", len(events))

        return events

    except Exception as error:
        print("[HATA] TFF:", error)
        save_source_check("TFF", "error", 0, error)
        return []


def main():
    print("=" * 55)
    print("TÜRKİYE BİLET TAKİP - SÜPER LİG")
    print("Zaman:", datetime.now(timezone.utc).isoformat())
    print("=" * 55)

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase GitHub Secrets eksik!")

    biletnerde_events = run_biletnerde()
    tff_events = run_tff()

    total = len(biletnerde_events) + len(tff_events)

    print("\n" + "=" * 55)
    print("TARAMA TAMAMLANDI")
    print("BiletNerde:", len(biletnerde_events))
    print("TFF:", len(tff_events))
    print("TOPLAM:", total)
    print("=" * 55)


if __name__ == "__main__":
    main()
