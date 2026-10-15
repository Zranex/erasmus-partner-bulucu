"""ESEP (European School Education Platform) – Okul eğitimi partner ilanlarını JSON:API üzerinden toplar.

Kaynak: school-education.ec.europa.eu  (eski adıyla eTwinning + School Education Gateway)
API: Drupal JSON:API — giriş gerektirmez, yapısal veri döner.

Kullanım:  python toplayici_esep.py --sayfa 10
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request

import veritabani

BASE = "https://school-education.ec.europa.eu"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ErasmusPartnerBulucu/1.0"
BEKLEME = 1.0
LIMIT = 50
EPOSTA_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Her endpoint için API adresi + opsiyonel filtre
ENDPOINTS = [
    # Okul mobilitesi (tümü)
    {"tip": "erasmus_mobility", "url": f"{BASE}/en/jsonapi/node/erasmus_mobility", "filtre": ""},
    # Ortaklık ilanları (tümü)
    {"tip": "erasmus_partnership", "url": f"{BASE}/en/jsonapi/node/erasmus_partnership", "filtre": ""},
    # eTwinning proje fikirleri (okul projeleri için potansiyel partner bulma)
    {"tip": "esep_etwinning_project_idea", "url": f"{BASE}/en/jsonapi/node/esep_etwinning_project_idea", "filtre": ""},
]

INCLUDE = "field_esep_organization,field_esep_organization.field_esep_country,field_esep_countries,field_esep_topics"

durum = {"calisiyor": False, "mesaj": "", "yeni": 0, "toplam": 0}


def getir_json(url, deneme=4):
    for i in range(deneme):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/vnd.api+json",
                "Accept-Language": "en",
            })
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
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


def _iliskili_bul(included, tip, id_):
    """JSON:API included dizisinden ilişkili kaydı bul."""
    for item in included:
        if item.get("type") == tip and item.get("id") == id_:
            return item
    return None


def _iliskili_idler(node, alan):
    """Bir node'un relationship alanındaki ID'leri döndür."""
    rel = node.get("relationships", {}).get(alan, {}).get("data")
    if not rel:
        return []
    if isinstance(rel, dict):
        return [rel.get("id")]
    return [r.get("id") for r in rel if r.get("id")]


def _tarih_ayristir(iso):
    if not iso:
        return None
    try:
        return str(iso)[:10]
    except Exception:
        return None


def node_to_ilan(node, included, endpoint_tip):
    attr = node.get("attributes", {})
    ilan = {"kaynak": "ESEP"}

    # URL
    slug = (attr.get("path", {}) or {}).get("alias") or ""
    if slug:
        ilan["url"] = BASE + slug
    else:
        ilan["url"] = f"{BASE}/en/jsonapi/node/{endpoint_tip}/{node['id']}"

    # Başlık
    ilan["baslik"] = attr.get("title", "")

    # Açıklama
    body = attr.get("body", {}) or {}
    summary_field = attr.get("field_esep_summary", {}) or {}
    aciklama_parts = []
    if isinstance(summary_field, dict) and summary_field.get("value"):
        aciklama_parts.append(re.sub(r"<[^>]+>", " ", summary_field["value"]).strip())
    if isinstance(body, dict) and body.get("value"):
        aciklama_parts.append(re.sub(r"<[^>]+>", " ", body["value"]).strip())
    ilan["aciklama"] = "\n".join(aciklama_parts)

    # Tarihler
    ilan["paylasim_tarihi"] = _tarih_ayristir(attr.get("changed") or attr.get("created"))
    ilan["gecerlilik_bitis"] = _tarih_ayristir(attr.get("field_esep_expiration_date"))

    # İlan türü
    turu = attr.get("field_erasmus_type") or []
    if isinstance(turu, list):
        ilan["ilan_turu"] = ", ".join(turu)
    elif isinstance(turu, str):
        ilan["ilan_turu"] = turu
    else:
        ilan["ilan_turu"] = endpoint_tip.replace("_", " ").title()

    # Kurum, ülke, e-posta (included'dan)
    org_ids = _iliskili_idler(node, "field_esep_organization")
    kurum, ulke, eposta, telefon = None, None, None, None
    for oid in org_ids:
        org = _iliskili_bul(included, "node--esep_organization", oid)
        if not org:
            continue
        oa = org.get("attributes", {})
        kurum = kurum or oa.get("title")
        eposta = eposta or oa.get("field_esep_organization_email") or oa.get("field_esep_principal_email")
        telefon = telefon or oa.get("field_esep_telephone")
        # Ülke: org -> field_esep_country relationship -> taxonomy_term
        if not ulke:
            country_rel = org.get("relationships", {}).get("field_esep_country", {}).get("data")
            if isinstance(country_rel, dict) and country_rel.get("id"):
                ct = _iliskili_bul(included, "taxonomy_term--esep_countries", country_rel["id"])
                if ct:
                    ulke = ct.get("attributes", {}).get("name")
            if not ulke:
                # Şehirden tahmin (son çare)
                ulke = oa.get("field_esep_country")
    ilan["kurum"] = kurum
    ilan["ulke"] = ulke
    if not eposta:
        m = EPOSTA_RE.search(ilan["aciklama"])
        eposta = m.group(0).rstrip(".") if m else None
    ilan["eposta"] = eposta

    # Aranan ülkeler
    country_ids = _iliskili_idler(node, "field_esep_countries")
    ulkeler = []
    for cid in country_ids:
        ct = _iliskili_bul(included, "taxonomy_term--esep_country", cid)
        if ct:
            ulkeler.append(ct.get("attributes", {}).get("name", ""))
    ilan["aranan_ulkeler"] = [u for u in ulkeler if u]

    # Konular
    topic_ids = _iliskili_idler(node, "field_esep_topics")
    konular = []
    for tid in topic_ids:
        tt = _iliskili_bul(included, "taxonomy_term--esep_topic", tid)
        if tt:
            konular.append(tt.get("attributes", {}).get("name", ""))
    ilan["konular"] = ", ".join(k for k in konular if k)

    # Diğer alanlar
    ilan["aranan_kurumlar"] = None
    ilan["diller"] = None
    ilan["konsorsiyum"] = None
    ilan["yorum_sayisi"] = None
    ilan["tepki_sayisi"] = None

    return ilan


def topla(sayfa_sayisi=10, yenile=False, log=print):
    durum.update(calisiyor=True, yeni=0, toplam=0, mesaj="ESEP başladı")
    c = veritabani.baglan()
    try:
        for ep in ENDPOINTS:
            tip = ep["tip"]
            base_url = ep["url"]
            filtre = ep.get("filtre", "")
            for p in range(sayfa_sayisi):
                offset = p * LIMIT
                url = f"{base_url}?page[offset]={offset}&page[limit]={LIMIT}&include={INCLUDE}&sort=-changed{filtre}"
                durum["mesaj"] = f"ESEP {tip} sayfa {p + 1}/{sayfa_sayisi}"
                log(durum["mesaj"])

                veri = getir_json(url)
                if not veri or not veri.get("data"):
                    log(f"  Sayfa {p + 1}: veri yok, durduruluyor.")
                    break

                included = veri.get("included", [])
                for node in veri["data"]:
                    durum["toplam"] += 1
                    try:
                        ilan = node_to_ilan(node, included, tip)
                    except Exception as ex:
                        log(f"  Ayrıştırma hatası: {ex}")
                        continue

                    if not yenile and veritabani.url_var_mi(c, ilan["url"]):
                        continue

                    veritabani.kaydet(c, ilan)
                    durum["yeni"] += 1
                    durum["mesaj"] = f"ESEP: {ilan.get('ulke') or '?'} – {ilan['baslik'][:50]}"
                    log(f"  [+] {ilan.get('ulke') or '?':<12} {ilan['baslik'][:80]}")

                # Sonraki sayfa var mı?
                if not veri.get("links", {}).get("next"):
                    break
                time.sleep(BEKLEME)
            time.sleep(BEKLEME)

        durum["mesaj"] = f"ESEP bitti: {durum['yeni']} yeni ilan eklendi"
    finally:
        durum["calisiyor"] = False
        c.close()
    log(durum["mesaj"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sayfa", type=int, default=10, help="Her endpoint için sayfa sayısı")
    ap.add_argument("--yenile", action="store_true")
    a = ap.parse_args()
    topla(a.sayfa, a.yenile)
