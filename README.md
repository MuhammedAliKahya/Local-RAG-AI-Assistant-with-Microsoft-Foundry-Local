# 🚀 Offline Local RAG AI Assistant

Microsoft Foundry Local runtime ve Qwen 2.5 (0.5B) yerel dil modelini kullanarak geliştirilmiş, tamamen çevrimdışı (offline) çalışan akıllı döküman soru-cevap asistanı.

## 🛠️ Özellikler
- **%100 Offline & Yerel Çalışma:** Sıfır bulut bağımlılığı ve sıfır API ücreti.
- **Vektör Veritabanı:** BAAI/bge-small-en-v1.5 embedding modeli ve SQLite entegrasyonu.
- **Halüsinasyon Kalkanı (Strict Guardrails):** Dökümanda yer almayan bilgiye uydurma cevap vermeyi reddeder.
- **Kaynak Gösterme (Citation):** Yanıtları dökümandaki ilgili paragrafa referans göstererek verir.
- **Performans Ölçümü:** Milisaniye bazlı vektör arama ve yanıt üretim metrikleri.

## 🚀 Çalıştırma
```bash
pip install -r requirements.txt
py main.py