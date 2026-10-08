"""Erasmus+ Project Results Platform – Tamamlanmış KA210/KA220 okul projelerinden potansiyel partner bulur.

Mantık: Daha önce başarılı proje yapmış okullar iyi partner adayıdır.
API: ec.europa.eu/programmes/erasmus-plus/projects sitesinden HTML ayrıştırma.

Kullanım:  python toplayici_sonuclar.py --sayfa 5
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request

import veritabani

BASE = "https://ec.europa.eu/programmes/erasmus-plus/projects"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ErasmusPartnerBulucu/1.0"
BEKLEME = 2.0

# KA210-SCH ve KA220-SCH projeleri için arama URL'leri
ARAMALAR = [
    {
        "ad": "KA210-SCH",
        "url": f"{BASE}/eplus-project-details/search?keywords=&keyActionRefs=KA210-SCH&educationSectors=School%20Education&budgetMax=&status=&sort=startDate:desc",
    },
    {
        "ad": "KA220-SCH",
        "url": f"{BASE}/eplus-project-details/search?keywords=&keyActionRefs=KA220-SCH&educationSectors=School%20Education&budgetMax=&status=&sort=startDate:desc",
    },
]

durum = {"calisiyor": False, "mesaj": "", "yeni": 0, "toplam": 0}


def getir(url, deneme=3):
    for i in range(deneme):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (i + 1))
                continue
            if e.code in (404, 403):
                return None
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return None


def satirlara(h):
    h = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", h, flags=re.S)
    h = re.sub(r"<br\s*/?>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", h))
    return [re.sub(r"\s+", " ", s).strip() for s in t.splitlines() if s.strip()]


def proje_listesi_ayristir(h):
    """Arama sonuç sayfasından proje linklerini çıkarır."""
    return list(dict.fromkeys(re.findall(r'href="([^"]*eplus-project-details/[^"#?]+)"', h or "")))


def proje_detay_to_ilan(url, h, arama_adi):
    satir = satirlara(h)
    ilan = {"kaynak": "EU-Results", "url": url}

    # Başlık
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    ilan["baslik"] = html.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip() if title_m else (satir[0] if satir else "")

    # Açıklama
    desc_m = re.search(r"(?:Project summary|Summary|Objective)(.*?)(?:Partners|Coordinator|Key Action)", h, re.S | re.I)
    if desc_m:
        ilan["aciklama"] = re.sub(r"<[^>]+>", " ", desc_m.group(1)).strip()[:2000]
    else:
        ilan["aciklama"] = "\n".join(satir[:20])

    # Koordinatör ülke
    ulke_m = re.search(r"Coordinating.*?organisation.*?country[:\s]*([\w\s]+)", h, re.S | re.I)
    if not ulke_m:
        ulke_m = re.search(r"Country.*?:\s*([A-Z][\w\s]+?)(?:<|$)", h)
    ilan["ulke"] = ulke_m.group(1).strip() if ulke_m else None

    # Kurum
    org_m = re.search(r"(?:Coordinator|Organisation)[:\s]*([^<\n]+)", h, re.I)
    ilan["kurum"] = html.unescape(org_m.group(1)).strip() if org_m else None

    ilan["ilan_turu"] = arama_adi
    ilan["paylasim_tarihi"] = None
    ilan["gecerlilik_bitis"] = None
    ilan["aranan_ulkeler"] = []
    ilan["aranan_kurumlar"] = None
    ilan["diller"] = None
    ilan["konular"] = None
    ilan["konsorsiyum"] = None
    ilan["eposta"] = None
    ilan["yorum_sayisi"] = None
    ilan["tepki_sayisi"] = None

    return ilan


def topla(sayfa_sayisi=3, yenile=False, log=print):
    durum.update(calisiyor=True, yeni=0, toplam=0, mesaj="EU Results başladı")
    c = veritabani.baglan()
    try:
        for arama in ARAMALAR:
            for p in range(sayfa_sayisi):
                sep = "&" if "?" in arama["url"] else "?"
                url = arama["url"] + f"{sep}page={p}"
                durum["mesaj"] = f"EU Results {arama['ad']} sayfa {p + 1}/{sayfa_sayisi}"
                log(durum["mesaj"])

                h = getir(url)
                linkler = proje_listesi_ayristir(h)
                if not linkler:
                    log(f"  Proje bulunamadı, durduruluyor.")
                    break

                for yol in linkler[:20]:
                    proje_url = yol if yol.startswith("http") else f"https://ec.europa.eu{yol}"
                    durum["toplam"] += 1
                    if not yenile and veritabani.url_var_mi(c, proje_url):
                        continue
                    time.sleep(BEKLEME)
                    dh = getir(proje_url)
                    if not dh:
                        continue
                    try:
                        ilan = proje_detay_to_ilan(proje_url, dh, arama["ad"])
                    except Exception as ex:
                        log(f"  Hata {proje_url}: {ex}")
                        continue
                    veritabani.kaydet(c, ilan)
                    durum["yeni"] += 1
                    log(f"  [+] {ilan.get('ulke') or '?':<12} {ilan['baslik'][:80]}")
                time.sleep(BEKLEME)

        durum["mesaj"] = f"EU Results bitti: {durum['yeni']} yeni proje eklendi"
    finally:
        durum["calisiyor"] = False
        c.close()
    log(durum["mesaj"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sayfa", type=int, default=3)
    ap.add_argument("--yenile", action="store_true")
    a = ap.parse_args()
    topla(a.sayfa, a.yenile)
