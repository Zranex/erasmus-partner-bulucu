"""EPALE (Avrupa Komisyonu resmi platformu) partner arama ilanlarını toplar.

Kullanım:  python toplayici.py --sayfa 5
Siteyi yormamak için istekler arasında bekleme yapılır.
"""
import argparse
import datetime as dt
import html
import re
import sys
import time
import urllib.error
import urllib.request

import veritabani

BASE = "https://epale.ec.europa.eu"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ErasmusPartnerBulucu/1.0"
BEKLEME = 1.5

ETIKETLER = {
    "post type": "ilan_turu",
    "valid from": "gecerlilik_baslangic",
    "valid until": "gecerlilik_bitis",
    "organisation": "kurum",
    "contact": "iletisim",
    "i am looking for": "aranan_kurumlar",
    "looking for new consortium members": "konsorsiyum",
    "i am looking for organisations in the following countries": "aranan_ulkeler",
    "language(s)": "diller",
    "topic": "konular",
    "mobility direction": "hareketlilik_yonu",
}
BITIS = ("click the arrow", "register your organisation")
EPOSTA_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Sunucunun ilerlemeyi gösterebilmesi için
durum = {"calisiyor": False, "mesaj": "", "yeni": 0, "toplam": 0}


def getir(url, deneme=4):
    for i in range(deneme):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(15 * (i + 1))
                continue
            if e.code == 404:
                return None
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return None


def satirlara_cevir(h):
    m = re.search(r"<main.*?</main>", h, re.S)
    govde = m.group(0) if m else h
    govde = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", govde, flags=re.S)
    govde = re.sub(r"<br\s*/?>", "\n", govde)
    metin = html.unescape(re.sub(r"<[^>]+>", "\n", govde))
    return [re.sub(r"\s+", " ", s).strip() for s in metin.splitlines() if s.strip()]


def _kisa_tarih(s):
    """dd/mm/yy -> ISO"""
    m = re.search(r"(\d{2})/(\d{2})/(\d{2,4})", s or "")
    if not m:
        return None
    g, a, y = m.groups()
    y = int(y) + 2000 if len(y) == 2 else int(y)
    try:
        return dt.date(y, int(a), int(g)).isoformat()
    except ValueError:
        return None


def detay_ayristir(url, h):
    satir = satirlara_cevir(h)
    ilan = {"kaynak": "EPALE", "url": url}
    ilan["baslik"] = satir[0] if satir else url.rsplit("/", 1)[-1]
    ulke = re.search(r'field--name-field-request-country.*?title="([^"]+)"', h, re.S)
    ilan["ulke"] = ulke.group(1).strip() if ulke else None

    i_post = next((i for i, s in enumerate(satir) if s.startswith("Posted on")), None)
    i_det = next((i for i, s in enumerate(satir) if s == "Partnership Details"), len(satir))
    if i_post is not None:
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", satir[i_post])  # mm/dd/yyyy
        if m:
            try:
                ilan["paylasim_tarihi"] = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
            except ValueError:
                pass
    ilan["aciklama"] = "\n".join(satir[(i_post + 1 if i_post is not None else 1):i_det])

    alanlar, aktif = {}, None
    for s in satir[i_det + 1:]:
        anahtar = s.lower().rstrip(":").strip()
        if anahtar.startswith(BITIS):
            break
        if anahtar in ETIKETLER:
            aktif = ETIKETLER[anahtar]
            alanlar[aktif] = []
        elif aktif:
            alanlar[aktif].append(s)

    ilan["ilan_turu"] = ", ".join(alanlar.get("ilan_turu", [])) or None
    ilan["gecerlilik_bitis"] = _kisa_tarih(" ".join(alanlar.get("gecerlilik_bitis", [])))
    ilan["kurum"] = (alanlar.get("kurum") or [None])[0]
    ilan["aranan_ulkeler"] = alanlar.get("aranan_ulkeler", [])
    ilan["aranan_kurumlar"] = ", ".join(alanlar.get("aranan_kurumlar", []))
    ilan["diller"] = ", ".join(alanlar.get("diller", []))
    ilan["konular"] = ", ".join(alanlar.get("konular", []))
    k = " ".join(alanlar.get("konsorsiyum", [])).lower()
    ilan["konsorsiyum"] = 1 if k.startswith("yes") else 0 if k.startswith("no") else None
    e = EPOSTA_RE.search(ilan["aciklama"])
    ilan["eposta"] = e.group(0).rstrip(".") if e else None
    return ilan


def topla(sayfa_sayisi=5, yenile=False, log=print):
    durum.update(calisiyor=True, yeni=0, toplam=0, mesaj="Başladı")
    c = veritabani.baglan()
    try:
        for p in range(sayfa_sayisi):
            durum["mesaj"] = f"Liste sayfası {p + 1}/{sayfa_sayisi}"
            h = getir(f"{BASE}/en/partner-search?page={p}")
            linkler = list(dict.fromkeys(re.findall(r'href="(/en/partner-requests/[^"#?]+)"', h or "")))
            if not linkler:
                log(f"Sayfa {p}: ilan bulunamadı, durduruluyor.")
                break
            for yol in linkler:
                url = BASE + yol
                durum["toplam"] += 1
                if not yenile and veritabani.url_var_mi(c, url):
                    continue
                time.sleep(BEKLEME)
                dh = getir(url)
                if not dh:
                    continue
                try:
                    ilan = detay_ayristir(url, dh)
                except Exception as ex:  # tek ilan hatası tüm toplamayı durdurmasın
                    log(f"Ayrıştırma hatası {url}: {ex}")
                    continue
                veritabani.kaydet(c, ilan)
                durum["yeni"] += 1
                durum["mesaj"] = f"Sayfa {p + 1}: {ilan['baslik'][:60]}"
                log(f"[+] {ilan.get('ulke') or '?':<12} {ilan['baslik'][:80]}")
            time.sleep(BEKLEME)
        durum["mesaj"] = f"Bitti: {durum['yeni']} yeni ilan eklendi"
    finally:
        durum["calisiyor"] = False
        c.close()
    log(durum["mesaj"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sayfa", type=int, default=5, help="Taranacak liste sayfası sayısı")
    ap.add_argument("--yenile", action="store_true", help="Kayıtlı ilanları da yeniden çek")
    a = ap.parse_args()
    topla(a.sayfa, a.yenile)
