# Erasmus+ Partner Bulucu

Erasmus+ ortak arama ilanlarını toplar, olumlu dönüş ihtimaline göre puanlar ve takip etmeni sağlar.

## Çalıştırma
`baslat.bat` dosyasına çift tıkla → tarayıcıda http://localhost:8765 açılır. (Python 3 gerekli, ek kütüphane yok.)

- **EPALE'den ilan çek**: Avrupa Komisyonu'nun resmi EPALE platformundaki partner ilanlarını toplar.
- **Facebook ilanı ekle**: Facebook'ta gördüğün ilanın linkini, metnini, yorum/tepki sayısını gir.
- Komut satırından toplama: `python toplayici.py --sayfa 10`

## Puanlama (0-100)
| Bileşen | Ağırlık | Mantık |
|---|---|---|
| Tazelik | 20 | Yeni ilan = daha az kişi yazmış (14 günlük yarı ömür) |
| Rekabet | 20 | Az yorum/tepki = az rakip. Veri yoksa tazelikten tahmin |
| Türkiye uyumu | 20 | Türkiye'yi arıyor mu / ülke kısıtı var mı |
| Ülke | 15 | Türk kurumlarıyla ortaklık sıklığı (sezgisel tablo) |
| Okul uyumu | 15 | Okul / öğretmen / KA2 anahtar kelimeleri |
| İletişim | 5 | Doğrudan e-posta var mı |
| Konsorsiyum | 5 | Yeni konsorsiyum üyesi arıyor mu |

Süresi dolan ilanlar ×0.2, Türkiye'den verilen ilanlar ×0.3. Tüm ağırlıklar ve ülke puanları `ayarlar.json` içinde.
