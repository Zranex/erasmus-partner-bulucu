"""İlan puanlama algoritması: olumlu dönüş alma ihtimalini 0-100 arası tahmin eder.

Bileşenler (her biri 0-1, ayarlar.json'daki ağırlıklarla birleştirilir):
  tazelik        : Yeni ilanlara henüz az kişi yazmıştır (yarı ömür modeli).
  rekabet        : Yorum/tepki az ise rakip az demektir. Veri yoksa tazelikten tahmin edilir.
  turkiye_uyumu  : İlan Türkiye'yi arıyor mu, yoksa Türkiye'yi dışlayan bir ülke listesi mi var?
  ulke           : İlanı veren ülkenin Türk kurumlarıyla ortaklık geçmişi / ajans bütçesi (sezgisel tablo).
  okul_uyumu     : Okul eğitimi ve KA2 ortaklığıyla ilgili anahtar kelimeler.
  iletisim       : Doğrudan e-posta var mı?
  konsorsiyum    : Yeni konsorsiyum üyesi arıyor mu?
Süresi dolmuş ilanların puanı 0.2 ile çarpılır.
"""
import datetime as dt
import json
import math
import re
from pathlib import Path

AYAR_YOLU = Path(__file__).parent / "ayarlar.json"
TR_ADLARI = ("turkey", "türkiye", "turkiye", "turkei", "türkei", "turquie", "turchia", "turquía", "turcja")


def ayarlari_yukle():
    return json.loads(AYAR_YOLU.read_text(encoding="utf-8"))


def _tarih(iso):
    if not iso:
        return None
    try:
        return dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def puanla(ilan, ayar=None):
    ayar = ayar or ayarlari_yukle()
    bugun = dt.date.today()
    metin = " ".join(
        str(ilan.get(k) or "") for k in ("baslik", "aciklama", "konular", "aranan_kurumlar", "ilan_turu")
    ).lower()
    s, neden = {}, []

    def n(tip, yazi):
        neden.append({"tip": tip, "metin": yazi})

    # 1) Tazelik
    pt = _tarih(ilan.get("paylasim_tarihi"))
    if pt is None:
        s["tazelik"] = 0.5
        n("~", "Paylaşım tarihi bilinmiyor")
    else:
        gun = max((bugun - pt).days, 0)
        s["tazelik"] = 0.5 ** (gun / ayar.get("tazelik_yari_omur_gun", 14))
        if gun <= 3:
            n("+", f"Çok yeni ilan ({gun} gün önce)")
        elif gun <= 14:
            n("+", f"Yeni ilan ({gun} gün önce)")
        elif gun > 45:
            n("-", f"Eski ilan ({gun} gün önce), muhtemelen ortaklar bulundu")

    # 2) Rekabet (etkileşim)
    yc, tc = ilan.get("yorum_sayisi"), ilan.get("tepki_sayisi")
    if yc in (None, "") and tc in (None, ""):
        s["rekabet"] = 0.3 + 0.5 * s["tazelik"]
        n("~", "Etkileşim verisi yok, tazeliğe göre tahmin edildi")
    else:
        yuk = int(yc or 0) + 0.3 * int(tc or 0)
        s["rekabet"] = 1 / (1 + yuk / 5)
        if int(yc or 0) == 0:
            n("+", "Hiç yorum yok, rakip az: ilk yazan sen ol!")
        elif int(yc or 0) >= 20:
            n("-", f"{yc} yorum var, rekabet yüksek")
        else:
            n("~", f"{yc} yorum var")

    # 3) Türkiye uyumu
    aranan = ilan.get("aranan_ulkeler") or []
    aranan_kucuk = [a.lower() for a in aranan]
    if any(t in metin for t in TR_ADLARI) or any(t in a for a in aranan_kucuk for t in TR_ADLARI):
        s["turkiye_uyumu"] = 1.0
        n("+", "Türkiye'den ortak arıyor / Türkiye'yi anıyor")
    elif not aranan:
        s["turkiye_uyumu"] = 0.75
        n("+", "Ülke kısıtı yok, tüm ülkelere açık")
    else:
        s["turkiye_uyumu"] = 0.1
        n("-", "Sadece şu ülkeleri arıyor: " + ", ".join(aranan[:6]) + (" ..." if len(aranan) > 6 else ""))

    # 4) Ülke
    ulke = (ilan.get("ulke") or "").strip()
    tablo = ayar.get("ulke_puanlari", {})
    s["ulke"] = tablo.get(ulke, ayar.get("varsayilan_ulke_puani", 0.5)) if ulke else 0.5
    if ulke.lower() in TR_ADLARI:
        n("-", "İlan sahibi Türkiye'den (aynı ülkeden ortak olamazsınız)")
    elif s["ulke"] >= 0.85:
        n("+", f"{ulke}: Türk okullarıyla sık ortaklık kuran ülke")
    elif ulke and s["ulke"] <= 0.4:
        n("-", f"{ulke}: ortaklık ihtimali düşük ülke")

    # 5) Okul / KA210 uyumu (lise + öğrenci değişimi + küçük ölçekli ortaklık)
    okul = sum(1 for k in ayar.get("okul_anahtar_kelimeleri", []) if k in metin)
    ka210 = any(k in metin for k in ayar.get("ka210_anahtar_kelimeleri", []))
    ka2 = ka210 or any(k in metin for k in ayar.get("ka2_anahtar_kelimeleri", []))
    yetiskin = sum(1 for k in ayar.get("yetiskin_anahtar_kelimeleri", []) if k in metin)
    ogrenci_degisim = sum(1 for k in ayar.get("ogrenci_degisim_kelimeleri", []) if k in metin)
    sadece_ka1 = "key action 1" in metin and not ka2

    # Sadece hoca/öğretmen mobilitesi tespiti (öğrenci gidemez!)
    hoca_kelimeleri = ["job shadowing", "teacher training", "teacher mobility",
                       "staff mobility", "staff training", "professional development",
                       "teachers only", "for teachers", "course for teacher",
                       "structured course", "observation visit", "teaching methodology",
                       "teacher exchange", "job shadow", "shadowing experience",
                       "shadowing partner", "shadowing host", "teacher job",
                       "invitation to job", "reciprocal job"]
    ogrenci_kelimeleri = ["student exchange", "student mobility", "pupil exchange",
                          "pupil mobility", "group mobility", "youth exchange",
                          "exchange of student", "exchange of pupil", "mobility of student",
                          "mobility of pupil", "school exchange", "host student",
                          "hosting student", "receive student", "send student",
                          "young people", "teenager", "aged 14", "aged 15",
                          "aged 16", "aged 17", "aged 13", "year old student",
                          "year-old student", "blended mobility",
                          "students", "pupils", "group of pupil"]
    hoca_hit = sum(1 for k in hoca_kelimeleri if k in metin)
    ogrenci_hit = sum(1 for k in ogrenci_kelimeleri if k in metin)
    sadece_hoca = hoca_hit >= 1 and ogrenci_hit == 0

    uyum = 0.20 + 0.10 * min(okul, 4) + (0.35 if ka210 else 0.2 if ka2 else 0)
    if ogrenci_degisim >= 2:
        uyum += 0.25
        n("+", "Öğrenci değişimi / hareketliliği içeriyor — tam aradığınız!")
    elif ogrenci_degisim == 1:
        uyum += 0.15
        n("+", "Öğrenci odaklı proje")
    if ka210:
        n("+", "KA210 (küçük ölçekli ortaklık) ilanı: tam aradığınız!")
    elif ka2:
        n("+", "KA2 / ortaklık projesi")
    if okul >= 2:
        n("+", "Okul / lise eğitimiyle ilgili")

    # Sadece hoca mobilitesi → öğrenci gidemez, çok düşük puan
    if sadece_hoca:
        uyum *= 0.20
        n("-", "⛔ Sadece öğretmen mobilitesi (job shadowing / kurs) — öğrenci katılamaz!")
    elif hoca_hit >= 2 and ogrenci_hit <= 1:
        uyum *= 0.50
        n("-", "Ağırlıklı öğretmen odaklı, öğrenci katılımı belirsiz")

    if yetiskin >= 2 and okul < 2 and ogrenci_degisim == 0:
        uyum *= 0.35
        n("-", "Yetişkin eğitimi odaklı (lise öğrencileri için uygun değil)")
    elif yetiskin and okul < 2:
        uyum *= 0.6
        n("-", "Yetişkin eğitimi içerikli (lise uygunluğu düşük)")
    if sadece_ka1 and ogrenci_degisim == 0 and not sadece_hoca:
        uyum *= 0.7
        n("-", "Sadece KA1 hareketlilik (KA210 değil)")
    s["okul_uyumu"] = min(1.0, uyum)

    # 6) İletişim
    s["iletisim"] = 1.0 if ilan.get("eposta") else 0.4
    if ilan.get("eposta"):
        n("+", "Doğrudan e-posta adresi var")

    # 7) Konsorsiyum
    k = ilan.get("konsorsiyum")
    s["konsorsiyum"] = 1.0 if k == 1 else 0.5
    if k == 1:
        n("+", "Yeni konsorsiyum üyesi arıyor")

    w = ayar.get("agirliklar", {})
    toplam_w = sum(w.get(k, 0) for k in s) or 1
    puan = 100 * sum(s[k] * w.get(k, 0) for k in s) / toplam_w

    gb = _tarih(ilan.get("gecerlilik_bitis"))
    suresi_doldu = gb is not None and gb < bugun
    if suresi_doldu:
        puan *= 0.2
        n("-", f"Süresi dolmuş ({gb.isoformat()})")
    elif gb is not None and (gb - bugun).days <= 14:
        n("~", f"Son tarih yakın: {gb.isoformat()}")
    if ulke.lower() in TR_ADLARI:
        puan *= 0.3

    puan = round(puan, 1)
    etiket = "Yüksek" if puan >= 70 else "Orta" if puan >= 50 else "Düşük"
    return {
        "puan": puan,
        "etiket": etiket,
        "suresi_doldu": suresi_doldu,
        "alt_puanlar": {k: round(v, 2) for k, v in s.items()},
        "nedenler": neden,
    }


EPOSTA_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def metinden_ozellik_cikar(metin):
    """Facebook vb. yerden yapıştırılan ilan metninden temel bilgileri çıkarır."""
    alt = (metin or "").lower()
    eposta = EPOSTA_RE.search(metin or "")
    tur = None
    for kalip, ad in (("ka220", "KA220"), ("ka210", "KA210"), ("ka2", "KA2"), ("ka122", "KA122"),
                      ("ka121", "KA121"), ("ka1", "KA1"), ("job shadowing", "KA1 (job shadowing)")):
        if kalip in alt:
            tur = ad
            break
    return {"eposta": eposta.group(0).rstrip(".") if eposta else None, "ilan_turu": tur}
