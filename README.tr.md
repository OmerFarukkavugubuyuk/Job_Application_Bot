# Handshake Job Bot

[🇬🇧 English](README.md) | 🇹🇷 Türkçe

**Özellikle [Handshake](https://joinhandshake.com) için** (öğrenci iş ve staj platformu) geliştirilmiş bir otomasyon botu. Handshake'teki ilan arama sonuçlarını tarar, yazılım/IT ile ilgili ilanları seçer, her ilan için Google Gemini ile **ilana özel CV ve ön yazı (cover letter)** hazırlar ve başvuruyu Handshake'in Quick Apply formu üzerinden gönderir.

> **Uyarı:** Bu kişisel bir öğrenme projesidir. Otomatik başvuru, Handshake'in kullanım şartlarına veya işverenlerin beklentilerine aykırı olabilir; üretilen belgeler de düşünülmüş, kişisel bir başvurunun yerini tutmaz. Kullanım tamamen kendi sorumluluğundadır.

---

## İçindekiler

1. [Nasıl çalışır?](#nasıl-çalışır)
2. [Gereksinimler](#gereksinimler)
3. [Kurulum](#kurulum)
4. [`master_cv.json` dosyanı oluşturma](#master_cvjson-dosyanı-oluşturma)
5. [Botu çalıştırma](#botu-çalıştırma)
6. [Çıktı dosyaları](#çıktı-dosyaları)
7. [Özelleştirme](#özelleştirme)
8. [Sınırlamalar](#sınırlamalar)
9. [Proje dosyaları](#proje-dosyaları)
10. [Güvenlik](#güvenlik)

---

## Nasıl çalışır?

1. **Manuel giriş.** Bot bir Chromium penceresi açar (Playwright). Handshake'e girişi sen yaparsın ve terminalde ENTER'a basarsın. Kod hiçbir şifre veya oturum bilgisi saklamaz.
2. **Sayfa taraması.** Handshake ilan aramanın sayfalarını (sayfa başına 25 ilan) gezer ve ilan ID'lerini toplar. Bir sayfa 3 denemede yüklenmezse sonraki sayfaya geçer. Bir sayfada hiç ilan kalmayınca durur.
3. **Atlama kontrolleri.** Her ilanı açar; daha önce başvurduysan, *Quick apply / Apply* butonu yoksa veya buton pasifse ilanı atlar.
4. **Uygunluk filtresi.** Anahtar kelime filtresi (`TITLE_INCLUDE`, `DESC_INCLUDE` ve kısaltma eşleştirici) başlık ve açıklamada yazılım / IT / donanım / veri / yapay zekâ / güvenlik terimlerini arar. Eşleşmeyen ilanlar atlanır.
5. **Gemini ile ilana özel belgeler.** İlan açıklaması ve `master_cv.json` Google Gemini'ye gönderilir. Bir model hata verirse veya zaman aşımına uğrarsa listedeki sıradaki model denenir.
   - Yapay zekâ bir yazar gibi değil, bir CV **editörü** gibi çalışır: yalnızca master CV'de zaten var olan içeriği *seçebilir ve yeniden sıralayabilir*.
   - Bir **doğrulama katmanı** her sonucu kontrol eder. Master CV'de olmayan teknoloji, araç, sayı veya kelime; abartılı ifadeler ("passionate", "cutting-edge", "robust" gibi); eksik deneyim kayıtları; yanlış madde metinleri; yanlış uzunlukta veya biçimde ön yazı içeren çıktıyı reddeder.
   - Doğrulama başarısız olursa sorunlar geri bildirim olarak yapay zekâya gönderilir ve yeniden denenir (en fazla `MAX_TRIES = 3`).
6. **PDF oluşturma.** Markdown çıktısı HTML'e çevrilir ve Playwright ile PDF'e yazdırılır. CV, **tek sayfaya** sığması için otomatik küçültülür.
7. **Gönderim ve doğrulama.** Bot Quick Apply formunu açar, ekli belgeleri üretilen `cv.pdf` ve `cover_letter.pdf` ile değiştirir, gönderir ve başvuruyu *Withdraw application* butonunu bekleyerek **doğrular**. Her ilanın sonucu `applied`, `skipped` veya `failed` olarak sayılır.
8. **Kayıt.** Her adım `job_bot.log` dosyasına yazılır ve `debug/` klasörüne ekran görüntüsü kaydedilir. Sonunda sayıları içeren bir özet yazdırılır.

---

## Gereksinimler

- Python 3.10 veya üstü (yazar Python 3.12 ile çalıştırdı)
- Bir Handshake hesabı
- Bir [Google Gemini API anahtarı](https://aistudio.google.com/)
- Playwright'ın Chromium tarayıcısı

---

## Kurulum

```bash
git clone <repo-adresin>
cd handshake-job-bot

python -m venv venv
# Windows:      venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 1. Ortam değişkenleri

`.env.example` dosyasını `.env` olarak kopyala ve iki değeri de doldur:

```
GEMINI_API_KEY=your_gemini_api_key_here
HANDSHAKE_SEARCH_ID=your_search_id_here
```

- `GEMINI_API_KEY`: [Google AI Studio](https://aistudio.google.com/) üzerinden oluştur.
- `HANDSHAKE_SEARCH_ID`: Handshake'te botun taramasını istediğin ilan aramasını aç (önce filtrelerini uygula). Adres çubuğunda URL `https://app.joinhandshake.com/job-search/<SAYI>?...` şeklinde görünür. Bu sayıyı kopyala.

### 2. Master CV'n

`master_cv.example.json` dosyasını `master_cv.json` olarak kopyala ve örnek metinleri kendi bilgilerinle değiştir. Kesin kurallar için sonraki bölüme bak.

---

## `master_cv.json` dosyanı oluşturma

`master_cv.json` senin **tek doğru kaynağındır**. Bot asla içerik uydurmaz; yalnızca burada yazdıklarını seçer ve sıralar. Dosya `.gitignore` içinde olduğu için kişisel bilgilerin asla Git'e eklenmez.

| Anahtar | Tür | Notlar |
|---|---|---|
| `name` | metin | CV başlığında ve ön yazı imzasında kullanılır |
| `contact` | nesne | `location`, `email`, `linkedin`, `github` (hepsi CV başlığında kullanılır) |
| `summary` | metin | Temel özet metnin |
| `skills.programming_languages` | liste | **Her öğe üretilen CV'de yer almak zorundadır** |
| `skills.frameworks_and_platforms` | liste | **Her öğe üretilen CV'de yer almak zorundadır** |
| `skills.other_skills` | liste | İlana uygunluğa göre sıralanabilir |
| `skills.spoken_languages` | liste | Beceriler bölümüne otomatik eklenir |
| `experience` | liste | Her kayıtta `role`, `company`, `dates`, `bullets` bulunur. Tüm kayıtlar ve maddeler kelimesi kelimesine korunur |
| `projects` | liste | `name`, isteğe bağlı `link` ve `bullets` içeren projeler. Kelimesi kelimesine korunur |
| `projects` (grup) | nesne | `name` ve `items` (liste) içeren tek bir proje nesnesi. CV'de bu öğelerden **4 ila 6** tanesi bulunmalıdır, bu yüzden en az 4 öğe yaz |
| `education` | liste | Her kayıtta `school`, `location`, `dates`, `degree` bulunur |
| `certifications` | liste | İsteğe bağlı |

Önemli noktalar:

- Küçük projeler grubunun adı **`Additional Independent Projects (C#)`** olmalıdır, çünkü bu başlık `CV_STRUCTURE` içinde sabit yazılıdır. Farklı bir ad istersen `handshake_bot.py` içindeki `CV_STRUCTURE` ile JSON dosyanda birlikte değiştir.
- Üretilen CV'deki bir madde ancak master CV'deki bir maddeyle eşleşirse kabul edilir (karşılaştırma tire türlerini, fazla boşlukları ve sondaki noktayı yok sayar).
- Maddelerini dikkatle ve doğru yaz. Her başvuruda tam olarak yazdığın gibi kullanılırlar.

---

## Botu çalıştırma

```bash
python handshake_bot.py
```

1. Chromium penceresi Handshake giriş sayfasında açılır.
2. Elle giriş yap (varsa doğrulama adımı dahil), sonra terminalde **ENTER**'a bas.
3. Bot sayfaları taramaya ve başvurmaya başlar. Çalışmasını tarayıcıda ve terminalde izleyebilirsin. İstediğin an `Ctrl + C` ile durdurabilirsin.

---

## Çıktı dosyaları

| Dosya / klasör | Açıklama |
|---|---|
| `cv.pdf`, `cv.md` | İşlenen ilana özel CV (her ilanda üzerine yazılır) |
| `cover_letter.pdf`, `cover_letter.md` | İşlenen ilana özel ön yazı |
| `job_bot.log` | Botun yaptığı her şeyin ayrıntılı kaydı |
| `debug/` | Her adımın ekran görüntüsü |

Bunların hepsi `.gitignore` içindedir.

---

## Özelleştirme

Tüm ayarlar `handshake_bot.py` dosyasının başındadır:

- **İlan filtresi:** Hangi ilanların uygun sayılacağını değiştirmek için `TITLE_INCLUDE`, `DESC_INCLUDE` ve `ACRONYMS` listelerini düzenle.
- **AI denemeleri ve modeller:** `MAX_TRIES` doğrulama yeniden denemelerini belirler; model listesi `ask_ai()` içindedir.
- **Yasaklı içerik:** `TECH_TERMS` (master CV'de bulunmadan görünmemesi gereken teknolojiler) ve `BANNED_PHRASES` (abartılı ifadeler).
- **Promptlar:** CV ve ön yazı promptları `generate_cv_pdf()` ve `generate_cover_letter_pdf()` içindedir. Bazı ifadeler yazarın kendi profili için yazılmıştır (örneğin ön yazıda belirli bir üniversiteden söz edilmesiyle ilgili bir satır), bu yüzden promptları gözden geçirip kendi profiline uyarla.
- **Log dili:** Log mesajları ve kod yorumları Türkçedir.

---

## Sınırlamalar

- Bot, Handshake'in sayfa yapısına (CSS seçiciler ve `data-hook` öznitelikleri) bağlıdır. Handshake arayüzü değişirse seçicilerin güncellenmesi gerekebilir.
- Bot, Handshake içindeki Quick apply / Apply akışı için yazılmıştır. Farklı veya harici bir başvuru süreci kullanan ilanlar atlanabilir ya da hata verebilir.
- Anahtar kelime filtresi mükemmel değildir; bazı alakasız ilanlar geçebilir, bazı uygun ilanlar atlanabilir.
- Üretilen ön yazıların kalitesi, master CV'deki bilgilerle ve yapay zekâyla sınırlıdır.

---

## Proje dosyaları

| Dosya | Görevi |
|---|---|
| `handshake_bot.py` | Bot: filtre, AI üretimi, doğrulama, PDF oluşturma ve Handshake başvuru akışı |
| `master_cv.example.json` | Kendi `master_cv.json` dosyan için şablon |
| `.env.example` | `.env` dosyan için şablon (API anahtarı ve arama ID'si) |
| `requirements.txt` | Python bağımlılıkları |
| `.gitignore` | Gizli bilgileri, kişisel verileri ve üretilen dosyaları Git dışında tutar |
| `README.md`, `README.tr.md` | Dokümantasyon (İngilizce ve Türkçe) |

**Teknolojiler:** Python, Playwright, Google Gemini API (`google-generativeai`), Markdown, python-dotenv.

---

## Güvenlik

- `.env` dosyanı, API anahtarını veya `master_cv.json` dosyanı asla commit etme.
- Bir API anahtarı ifşa olursa hemen iptal edip yenisini oluştur.
- Bot Handshake şifreni asla saklamaz; girişi tarayıcı penceresinde elle yaparsın.
