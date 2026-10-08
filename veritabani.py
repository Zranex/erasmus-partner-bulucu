"""İlanların saklandığı SQLite veritabanı yardımcıları."""
import datetime as dt
import json
import sqlite3
from pathlib import Path

DB_YOLU = Path(__file__).parent / "veri" / "ilanlar.db"

ALANLAR = [
    "kaynak", "url", "baslik", "aciklama", "ulke", "kurum", "ilan_turu",
    "paylasim_tarihi", "gecerlilik_bitis", "aranan_ulkeler", "aranan_kurumlar",
    "diller", "konular", "konsorsiyum", "eposta", "yorum_sayisi", "tepki_sayisi",
]


def baglan():
    DB_YOLU.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_YOLU)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS ilanlar(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kaynak TEXT, url TEXT UNIQUE, baslik TEXT, aciklama TEXT, ulke TEXT,
            kurum TEXT, ilan_turu TEXT, paylasim_tarihi TEXT, gecerlilik_bitis TEXT,
            aranan_ulkeler TEXT, aranan_kurumlar TEXT, diller TEXT, konular TEXT,
            konsorsiyum INTEGER, eposta TEXT, yorum_sayisi INTEGER, tepki_sayisi INTEGER,
            durum TEXT DEFAULT 'Yeni', notlar TEXT DEFAULT '', eklenme TEXT)"""
    )
    return c


def kaydet(c, ilan):
    """İlanı ekler; aynı URL varsa günceller (durum ve notlar korunur)."""
    d = {k: ilan.get(k) for k in ALANLAR}
    if isinstance(d["aranan_ulkeler"], list):
        d["aranan_ulkeler"] = json.dumps(d["aranan_ulkeler"], ensure_ascii=False)
    if not d["url"]:
        d["url"] = None
    kolonlar = ",".join(ALANLAR)
    yer = ",".join("?" * len(ALANLAR))
    guncelle = ",".join(f"{k}=excluded.{k}" for k in ALANLAR if k not in ("url", "yorum_sayisi", "tepki_sayisi"))
    c.execute(
        f"INSERT INTO ilanlar({kolonlar},eklenme) VALUES({yer},?) "
        f"ON CONFLICT(url) DO UPDATE SET {guncelle}",
        [d[k] for k in ALANLAR] + [dt.datetime.now().isoformat(timespec="seconds")],
    )
    c.commit()


def url_var_mi(c, url):
    return c.execute("SELECT 1 FROM ilanlar WHERE url=?", (url,)).fetchone() is not None


def tumu(c):
    satirlar = []
    for r in c.execute("SELECT * FROM ilanlar"):
        d = dict(r)
        try:
            d["aranan_ulkeler"] = json.loads(d["aranan_ulkeler"] or "[]")
        except ValueError:
            d["aranan_ulkeler"] = []
        satirlar.append(d)
    return satirlar


def guncelle(c, ilan_id, alanlar):
    izinli = {"durum", "notlar", "yorum_sayisi", "tepki_sayisi", "ulke", "gecerlilik_bitis", "eposta"}
    alanlar = {k: v for k, v in alanlar.items() if k in izinli}
    if not alanlar:
        return
    c.execute(
        f"UPDATE ilanlar SET {','.join(f'{k}=?' for k in alanlar)} WHERE id=?",
        list(alanlar.values()) + [ilan_id],
    )
    c.commit()


def sil(c, ilan_id):
    c.execute("DELETE FROM ilanlar WHERE id=?", (ilan_id,))
    c.commit()
