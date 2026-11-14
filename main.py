
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone


def test_supabase_connection():
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL veya SUPABASE_KEY eksik!")

    endpoint = f"{supabase_url}/rest/v1/source_checks"

    data = {
        "source": "system_connection_test",
        "status": "success",
        "events_found": 0
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print("Supabase bağlantısı başarılı!")
            print("HTTP durumu:", response.status)
            print("Test kaydı veritabanına eklendi.")

    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Supabase HTTP hatası: {error.code} - {details}"
        )


def main():
    print("=" * 50)
    print("TURKIYE BILET TAKIP SISTEMI")
    print("Kontrol:", datetime.now(timezone.utc).isoformat())
    print("=" * 50)

    test_supabase_connection()

    print("İlk bağlantı testi tamamlandı.")


if __name__ == "__main__":
    main()
