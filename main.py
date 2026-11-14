
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser


SOURCES = [
    {
        "name": "BiletNerde",
        "url": "https://biletnerde.com/etkinlikler"
    },
    {
        "name": "TFF",
        "url": "https://www.tff.org/default.aspx"
    }
]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def check_source(source):
    request = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TurkiyeBiletTakip/1.0)",
            "Accept": "text/html,application/xhtml+xml"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw_html = response.read()

            charset = response.headers.get_content_charset() or "utf-8"
            html = raw_html.decode(charset, errors="replace")

            parser = PageParser()
            parser.feed(html)

            title = parser.title.strip()

            print("\n[BASARILI]", source["name"])
            print("HTTP:", response.status)
            print("Sayfa başlığı:", title[:200])
            print("HTML boyutu:", len(raw_html), "byte")

            return {
                "source": source["name"],
                "status": "success",
                "events_found": 0,
                "error_message": None
            }

    except Exception as error:
        message = str(error)[:500]

        print("\n[HATA]", source["name"])
        print(message)

        return {
            "source": source["name"],
            "status": "error",
            "events_found": 0,
            "error_message": message
        }


def save_results(results):
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL veya SUPABASE_KEY eksik. "
            "GitHub Secrets ayarlarını kontrol et."
        )

    endpoint = supabase_url.rstrip("/") + "/rest/v1/source_checks"

    for result in results:
        data = json.dumps(result).encode("utf-8")

        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            print(
                "[SUPABASE KAYDI]",
                result["source"],
                "HTTP:",
                response.status
            )


def main():
    print("=" * 50)
    print("TÜRKİYE BİLET TAKİP SİSTEMİ")
    print("KAYNAK ERİŞİM TESTİ")
    print("=" * 50)

    print("Kontrol zamanı:", datetime.now(timezone.utc).isoformat())

    results = []

    for source in SOURCES:
        results.append(check_source(source))

    save_results(results)

    successful = sum(
        1 for result in results
        if result["status"] == "success"
    )

    print("\n" + "=" * 50)
    print("KONTROL TAMAMLANDI")
    print("Başarılı kaynak:", successful)
    print("Toplam kaynak:", len(SOURCES))
    print("=" * 50)


if __name__ == "__main__":
    main()
