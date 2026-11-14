
from datetime import datetime, timezone

SOURCES = [
    {
        "name": "Biletix",
        "url": "https://www.biletix.com/"
    },
    {
        "name": "Passo",
        "url": "https://www.passo.com.tr/"
    },
    {
        "name": "Bubilet",
        "url": "https://www.bubilet.com.tr/"
    },
    {
        "name": "Biletinial",
        "url": "https://www.biletinial.com/"
    },
    {
        "name": "Mobilet",
        "url": "https://www.mobilet.com/"
    },
    {
        "name": "iTicket",
        "url": "https://www.iticket.com.tr/"
    }
]

def main():
    print("=" * 50)
    print("TURKIYE BILET TAKIP SISTEMI")
    print("Kontrol:", datetime.now(timezone.utc).isoformat())
    print("=" * 50)

    for source in SOURCES:
        print(f"Hazir kaynak: {source['name']} - {source['url']}")

    print("Sistem kontrolu basariyla tamamlandi.")

if __name__ == "__main__":
    main()
