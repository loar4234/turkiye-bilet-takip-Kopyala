
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser


SOURCES = [
    {
        "name": "KonserBul",
        "url": "https://konserbul.com.tr/"
    },
    {
        "name": "TFF",
        "url": "https://www.tff.org/default.aspx?lang=tr"
    }
]


class TitleParser(HTMLParser):
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
            "User-Agent": "Mozilla/5.0 (compatible; TurkiyeBiletTakip/1.0)"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
            parser = TitleParser()
            parser.feed(html)

            print(f"[BASARILI] {source['name']}")
            print("HTTP:", response.status)
            print("Sayfa:", parser.title.strip()[:150])

            return {
                "source": source["name"],
                "status": "success",
                "events_found": 0,
                "error_message": None
            }

    except Exception as error:
        message = str(error)[:500]
        print(f"[HATA] {source['name']}: {message}")

        return {
            "source": source["name"],
            "status": "error",
            "events_found": 0,
            "error_message": message
        }


def save_results(results):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]

    endpoint = f"{url}/rest/v1/source_checks"

    for result in results:
        data = json.dumps(result).encode("utf-8")

        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            print("Supabase kayıt:", result["source"], response.status)


def main():
    print("TURKIYE BILET TAKIP - KAYNAK TESTI")
    print(datetime.now(timezone.utc).isoformat())

    results = [check_source(source) for source in SOURCES]
    save_results(results)

    print("Kaynak kontrolü tamamlandı.")


if __name__ == "__main__":
    main()
