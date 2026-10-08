"""Yerel web sunucusu. Çalıştır:  python sunucu.py   ->  http://localhost:8765"""
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import puanlama
import toplayici
import toplayici_esep
import toplayici_sonuclar
import veritabani

import os

PORT = int(os.environ.get("PORT", 8765))
WEB = Path(__file__).parent / "web"

# Her kaynak için durum takibi
KAYNAKLAR = {
    "epale": {"modul": toplayici, "ad": "EPALE"},
    "esep": {"modul": toplayici_esep, "ad": "ESEP (Okul Eğitimi)"},
    "sonuclar": {"modul": toplayici_sonuclar, "ad": "EU Proje Sonuçları"},
}

# Birleşik toplama durumu
topla_durum = {"calisiyor": False, "mesaj": "", "yeni": 0, "toplam": 0}


def hepsini_topla(sayfa=5, kaynaklar=None):
    """Tüm kaynakları sırayla toplar."""
    if topla_durum["calisiyor"]:
        return
    topla_durum.update(calisiyor=True, yeni=0, toplam=0, mesaj="Toplama başladı...")
    secili = kaynaklar or list(KAYNAKLAR.keys())
    try:
        for anahtar in secili:
            kaynak = KAYNAKLAR.get(anahtar)
            if not kaynak:
                continue
            topla_durum["mesaj"] = f"{kaynak['ad']} taranıyor..."
            try:
                kaynak["modul"].topla(sayfa)
                topla_durum["yeni"] += kaynak["modul"].durum.get("yeni", 0)
                topla_durum["toplam"] += kaynak["modul"].durum.get("toplam", 0)
            except Exception as e:
                topla_durum["mesaj"] = f"{kaynak['ad']} hatası: {e}"
        topla_durum["mesaj"] = f"Bitti: {topla_durum['yeni']} yeni ilan eklendi (toplam {topla_durum['toplam']} tarandı)"
    finally:
        topla_durum["calisiyor"] = False


class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, veri, kod=200):
        b = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _govde(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            b = (WEB / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b)
        elif self.path == "/api/ilanlar":
            ayar = puanlama.ayarlari_yukle()
            c = veritabani.baglan()
            ilanlar = veritabani.tumu(c)
            c.close()
            for i in ilanlar:
                i.update(puanlama.puanla(i, ayar))
            ilanlar.sort(key=lambda x: x["puan"], reverse=True)
            self._json(ilanlar)
        elif self.path == "/api/topla":
            self._json(topla_durum)
        elif self.path == "/api/ayarlar":
            self._json(puanlama.ayarlari_yukle())
        elif self.path == "/api/kaynaklar":
            self._json({k: {"ad": v["ad"], "calisiyor": v["modul"].durum.get("calisiyor", False),
                            "mesaj": v["modul"].durum.get("mesaj", "")} for k, v in KAYNAKLAR.items()})
        else:
            self._json({"hata": "bulunamadı"}, 404)

    def do_POST(self):
        veri = self._govde()
        c = veritabani.baglan()
        try:
            if self.path == "/api/topla":
                if not topla_durum["calisiyor"]:
                    sayfa = int(veri.get("sayfa") or 5)
                    kaynaklar = veri.get("kaynaklar")  # None = hepsi
                    threading.Thread(target=hepsini_topla, args=(sayfa, kaynaklar), daemon=True).start()
                self._json({"ok": True})
            elif self.path == "/api/ilan":
                cikan = puanlama.metinden_ozellik_cikar(veri.get("aciklama", ""))
                for k, v in cikan.items():
                    if not veri.get(k):
                        veri[k] = v
                for k in ("yorum_sayisi", "tepki_sayisi"):
                    veri[k] = int(veri[k]) if str(veri.get(k, "")).strip().isdigit() else None
                if isinstance(veri.get("aranan_ulkeler"), str):
                    veri["aranan_ulkeler"] = [u.strip() for u in veri["aranan_ulkeler"].split(",") if u.strip()]
                veri.setdefault("kaynak", "Facebook")
                veritabani.kaydet(c, veri)
                self._json({"ok": True})
            elif self.path.startswith("/api/ilan/"):
                veritabani.guncelle(c, int(self.path.rsplit("/", 1)[-1]), veri)
                self._json({"ok": True})
            else:
                self._json({"hata": "bulunamadı"}, 404)
        except Exception as e:
            self._json({"hata": str(e)}, 400)
        finally:
            c.close()

    def do_DELETE(self):
        if self.path.startswith("/api/ilan/"):
            c = veritabani.baglan()
            veritabani.sil(c, int(self.path.rsplit("/", 1)[-1]))
            c.close()
            self._json({"ok": True})


if __name__ == "__main__":
    import socket
    sys.stdout.reconfigure(encoding="utf-8")
    veritabani.baglan().close()
    yerel = "--yerel" in sys.argv
    host = "127.0.0.1" if yerel else "0.0.0.0"
    port = PORT
    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)
    # Yerel IP adresini bul
    ip = "localhost"
    if not yerel:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
    print(f"Erasmus+ Partner Bulucu çalışıyor!")
    print(f"  Yerel:   http://localhost:{port}")
    if not yerel:
        print(f"  Ağda:    http://{ip}:{port}")
        print(f"  İnternet: cloudflared tunnel --url http://localhost:{port}")
    print(f"Kaynaklar: {', '.join(k['ad'] for k in KAYNAKLAR.values())}")
    print(f"Kapatmak için Ctrl+C")
    if "--tarayici-acma" not in sys.argv:
        threading.Timer(1, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    ThreadingHTTPServer((host, port), Isleyici).serve_forever()
