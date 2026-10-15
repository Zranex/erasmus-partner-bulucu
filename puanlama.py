"""İlan puanlama algoritması v2 — KA210-SCH (Small-scale School Partnerships) odaklı.

Bileşenler (her biri 0-1, ayarlar.json'daki ağırlıklarla birleştirilir):
  tazelik        : Yeni ilanlara henüz az kişi yazmıştır (yarı ömür modeli).
  rekabet        : Yorum/tepki az ise rakip az demektir. Veri yoksa tazelikten tahmin.
  turkiye_uyumu  : İlan Türkiye'yi arıyor mu?
  ulke           : İlanı veren ülkenin Türk okullarıyla ortaklık geçmişi.
  ka210_uyumu    : KA210-SCH tipi + okul eğitimi + öğrenci katılımı + konu uyumu.
  iletisim       : Doğrudan e-posta var mı?
  konsorsiyum    : Yeni üye arıyor mu?

Cezalar:
  Süresi dolmuş      → ×0.2
  Türk ilanı         → ×0.3
  Sadece hoca (JS)   → ×0.20
  Yetişkin eğitimi   → ×0.25
  VET (mesleki)      → ×0.40
  Youth (gençlik)    → ×0.50
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


def _say(kelimeliste, metin):
    return sum(1 for k in kelimeliste if k in metin)


def _var(kelimeliste, metin):
    return any(k in metin for k in kelimeliste)


def puanla(ilan, ayar=None):
    ayar = ayar or ayarlari_yukle()
    bugun = dt.date.today()
    metin = " ".join(
        str(ilan.get(k) or "") for k in ("baslik", "aciklama", "konular", "aranan_kurumlar", "ilan_turu")
    ).lower()
    s, neden = {}, []

    def n(tip, yazi):
        neden.append({"tip": tip, "metin": yazi})

    # ═══════════════════════════════════════
    # 1) Tazelik
    # ═══════════════════════════════════════
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

    # ═══════════════════════════════════════
    # 2) Rekabet
    # ═══════════════════════════════════════
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

    # ═══════════════════════════════════════
    # 3) Türkiye uyumu
    # ═══════════════════════════════════════
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

    # ═══════════════════════════════════════
    # 4) Ülke
    # ═══════════════════════════════════════
    ulke = (ilan.get("ulke") or "").strip()
    tablo = ayar.get("ulke_puanlari", {})
    s["ulke"] = tablo.get(ulke, ayar.get("varsayilan_ulke_puani", 0.5)) if ulke else 0.5
    if ulke.lower() in TR_ADLARI:
        n("-", "İlan sahibi Türkiye'den (aynı ülkeden ortak olamazsınız)")
    elif s["ulke"] >= 0.85:
        n("+", f"{ulke}: Türk okullarıyla sık ortaklık kuran ülke")
    elif ulke and s["ulke"] <= 0.4:
        n("-", f"{ulke}: ortaklık ihtimali düşük ülke")

    # ═══════════════════════════════════════
    # 5) KA210-SCH uyumu (ANA SKORLAMA)
    # ═══════════════════════════════════════

    # --- Proje tipi tespiti ---
    ka210_sch = _var(ayar.get("ka210_sch_kelimeleri", []), metin)
    ka210 = ka210_sch or _var(ayar.get("ka210_genel_kelimeleri", []), metin)
    ka220_sch = _var(ayar.get("ka220_sch_kelimeleri", []), metin)
    ka2 = ka210 or ka220_sch or _var(ayar.get("ka2_kelimeleri", []), metin)
    ka1 = _var(ayar.get("ka1_kelimeleri", []), metin)

    # --- Sektör tespiti ---
    okul = _say(ayar.get("okul_sch_kelimeleri", []), metin)
    yetiskin = _say(ayar.get("yetiskin_kelimeleri", []), metin)
    vet = _say(ayar.get("vet_kelimeleri", []), metin)
    youth = _say(ayar.get("youth_kelimeleri", []), metin)
    ogrenci = _say(ayar.get("ogrenci_kelimeleri", []), metin)

    # --- Hoca-only tespiti ---
    hoca_hit = _say(ayar.get("hoca_kelimeleri", []), metin)
    sadece_hoca = hoca_hit >= 1 and ogrenci == 0

    # --- Konu uyumu ---
    konu = _say(ayar.get("ka210_konulari", []), metin)

    # === Skor hesapla ===
    uyum = 0.15  # taban

    # Proje tipi bonusu
    if ka210_sch:
        uyum += 0.45
        n("+", "🎯 KA210-SCH — tam aradığınız proje tipi!")
    elif ka210:
        uyum += 0.35
        n("+", "KA210 küçük ölçekli ortaklık ilanı")
    elif ka220_sch:
        uyum += 0.25
        n("+", "KA220-SCH ortaklık projesi")
    elif ka2:
        uyum += 0.18
        n("+", "KA2 ortaklık projesi")
    elif ka1 and not sadece_hoca:
        uyum += 0.05
        n("~", "KA1 hareketlilik projesi (KA210 değil)")

    # Okul eğitimi bonusu
    if okul >= 3:
        uyum += 0.15
        n("+", "Okul eğitimi odaklı ilan")
    elif okul >= 1:
        uyum += 0.08
        n("+", "Okul eğitimiyle ilgili")

    # Öğrenci katılımı bonusu
    if ogrenci >= 3:
        uyum += 0.20
        n("+", "Öğrenci değişimi / hareketliliği — tam aradığınız!")
    elif ogrenci >= 1:
        uyum += 0.10
        n("+", "Öğrenci odaklı proje")

    # Konu uyumu bonusu
    if konu >= 3:
        uyum += 0.10
        n("+", "KA210'a uygun konular içeriyor")
    elif konu >= 1:
        uyum += 0.04

    # === CEZALAR ===

    # Sadece hoca mobilitesi
    if sadece_hoca:
        uyum *= 0.20
        n("-", "⛔ Sadece öğretmen mobilitesi — öğrenci katılamaz!")
    elif hoca_hit >= 2 and ogrenci <= 1:
        uyum *= 0.50
        n("-", "Ağırlıklı öğretmen odaklı, öğrenci katılımı belirsiz")

    # Yetişkin eğitimi
    if yetiskin >= 2 and okul < 2 and ogrenci == 0:
        uyum *= 0.25
        n("-", "⛔ Yetişkin eğitimi odaklı — lise öğrencileri için uygun değil")
    elif yetiskin >= 1 and okul < 2:
        uyum *= 0.55
        n("-", "Yetişkin eğitimi içerikli")

    # VET (mesleki eğitim) — okul da değilse ceza
    if vet >= 2 and okul < 2:
        uyum *= 0.40
        n("-", "Mesleki eğitim (VET) odaklı — genel lise için uygun değil")
    elif vet >= 1 and okul < 1:
        uyum *= 0.65
        n("-", "VET içerikli")

    # Youth (gençlik) — okul değilse ceza
    if youth >= 2 and okul < 1:
        uyum *= 0.50
        n("-", "Gençlik sektörü — okul eğitimi değil")

    # Sadece KA1 + öğrenci yok
    if ka1 and not ka2 and ogrenci == 0 and not sadece_hoca:
        uyum *= 0.60
        n("-", "Sadece KA1 hareketlilik (KA210 değil)")

    s["ka210_uyumu"] = min(1.0, uyum)

    # ═══════════════════════════════════════
    # 6) İletişim
    # ═══════════════════════════════════════
    s["iletisim"] = 1.0 if ilan.get("eposta") else 0.3
    if ilan.get("eposta"):
        n("+", "Doğrudan e-posta adresi var")
    else:
        n("-", "E-posta adresi yok")

    # ═══════════════════════════════════════
    # 7) Konsorsiyum
    # ═══════════════════════════════════════
    kons = ilan.get("konsorsiyum")
    if kons == 1:
        s["konsorsiyum"] = 1.0
        n("+", "Yeni konsorsiyum üyesi arıyor")
    elif "looking for partner" in metin or "partner search" in metin or "seeking partner" in metin:
        s["konsorsiyum"] = 0.9
        n("+", "Aktif olarak partner arıyor")
    elif "join" in metin and ("project" in metin or "ka210" in metin):
        s["konsorsiyum"] = 0.8
        n("+", "Projeye katılım teklifi")
    else:
        s["konsorsiyum"] = 0.5

    # ═══════════════════════════════════════
    # Toplam puan
    # ═══════════════════════════════════════
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
    etiket = "Yüksek" if puan >= 70 else "Orta" if puan >= 45 else "Düşük"
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
    for kalip, ad in (("ka210-sch", "KA210-SCH"), ("ka220-sch", "KA220-SCH"),
                      ("ka210", "KA210"), ("ka220", "KA220"),
                      ("ka2", "KA2"), ("ka122-sch", "KA122-SCH"), ("ka121-sch", "KA121-SCH"),
                      ("ka122", "KA122"), ("ka121", "KA121"),
                      ("ka1", "KA1"), ("job shadowing", "KA1 (job shadowing)"),
                      ("small-scale", "KA210"), ("small scale", "KA210")):
        if kalip in alt:
            tur = ad
            break
    return {"eposta": eposta.group(0).rstrip(".") if eposta else None, "ilan_turu": tur}
