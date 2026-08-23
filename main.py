"""
====================================================================
PROJE: Offline Local RAG AI Assistant (Strict Guardrail & Similarity Gate)
ALTYAPI: Microsoft Foundry Local + Qwen 2.5 (0.5B) + BGE-small + SQLite
====================================================================
"""

import json
import os
import sqlite3
import time

from foundry_local_sdk import Configuration, FoundryLocalManager
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import numpy as np
from sentence_transformers import SentenceTransformer

# ====================================================================
# CONFIGURATION & CONSTANTS
# ====================================================================
PDF_PATH = "dokuman.pdf"
DB_PATH = "rag_memory.db"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
LLM_MODEL_NAME = "qwen2.5-0.5b"
CHUNK_SIZE = 400
CHUNK_OVERLAP = 40
TOP_K_RESULTS = 3
SIMILARITY_THRESHOLD = 0.45  # Bu değerin altındaki alakasız sorular doğrudan reddedilir.
FALLBACK_RESPONSE = "The provided document context does not contain information to answer this question."


# ====================================================================
# 1. STEP: DATA INGESTION & PIPELINE SETUP
# ====================================================================
def initialize_database():
    """PDF dökümanını okur, gürültüyü temizler, vektörleştirir ve SQLite veritabanına kaydeder."""
    print("📥 [1/4] PDF dökümanı taranıyor ve metin dilimleniyor...")

    if not os.path.exists(PDF_PATH):
        print(f"❌ Hata: '{PDF_PATH}' dosyası bulunamadı! Lütfen klasöre ekleyin.")
        exit(1)

    loader = PyPDFLoader(PDF_PATH)
    documents = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = text_splitter.split_documents(documents)

    filtered_chunks = []
    for c in chunks:
        content = c.page_content.strip()
        if "https://doi.org" in content and "Dergisi" in content:
            continue
        if content.startswith("References") or content.startswith("KAYNAKÇA"):
            continue
        filtered_chunks.append(content)

    print(f"--> {len(filtered_chunks)} adet optimize edilmiş metin parçası hazır.")
    print(f"🧠 [2/4] BGE Vektör Modeli ({EMBEDDING_MODEL_NAME}) yükleniyor...")
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print(f"💾 [3/4] SQLite Veritabanı ({DB_PATH}) güncelleniyor...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS documents")
    cursor.execute(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            embedding TEXT
        )
    """
    )

    for chunk_text in filtered_chunks:
        vector = embed_model.encode(
            chunk_text, normalize_embeddings=True
        ).tolist()
        cursor.execute(
            "INSERT INTO documents (content, embedding) VALUES (?, ?)",
            (chunk_text, json.dumps(vector)),
        )

    conn.commit()
    conn.close()
    print("--> Vektör veritabanı senkronize edildi!\n")
    return embed_model


# ====================================================================
# 2. STEP: VECTOR RETRIEVAL ENGINE
# ====================================================================
def search_similar_chunks(query, embed_model, top_k=TOP_K_RESULTS):
    """Kullanıcı sorusunu vektörleştirir ve Kosinüs Benzerliği hesaplar."""
    clean_query = query.strip().strip('"').strip("'")
    query_vector = embed_model.encode(clean_query, normalize_embeddings=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, content, embedding FROM documents")
    rows = cursor.fetchall()
    conn.close()

    results = []
    for doc_id, content, vector_str in rows:
        doc_vector = np.array(json.loads(vector_str))
        sim_score = float(np.dot(query_vector, doc_vector))
        results.append((doc_id, content, sim_score))

    results.sort(key=lambda x: x[2], reverse=True)
    return results[:top_k]


# ====================================================================
# 3. STEP: MAIN APPLICATION & SYSTEM EXECUTION
# ====================================================================
def main():
    embed_model = initialize_database()

    print(
        f"⚡ [4/4] Microsoft Foundry Local Runtime & LLM ({LLM_MODEL_NAME}) başlatılıyor..."
    )
    FoundryLocalManager.initialize(Configuration(app_name="local-rag-app"))
    model = FoundryLocalManager.instance.catalog.get_model(LLM_MODEL_NAME)
    model.download()
    model.load()
    client = model.get_chat_client()

    print("\n" + "=" * 65)
    print("🤖 OFFLINE LOCAL RAG AI ASSISTANT IS READY FOR DEMO!")
    print("Sıfır Halüsinasyon | Similarity Threshold Korumalı | Tam Yerel")
    print("=" * 65 + "\n")

    while True:
        try:
            soru = input("\nSoru girin (Çıkış için 'q'): ")
            if soru.lower() in ["çıkış", "exit", "q"]:
                print("RAG Asistanı kapatılıyor. İyi çalışmalar!")
                break

            if not soru.strip():
                continue

            # A) RETRIEVAL & BENCHMARK
            t0_retrieval = time.time()
            en_alakali_parcalar = search_similar_chunks(soru, embed_model)
            retrieval_time = time.time() - t0_retrieval

            en_yuksek_skor = en_alakali_parcalar[0][2] if en_alakali_parcalar else 0.0

            # B) DETERMINISTIC GUARDRAIL (Eşik Kontrolü)
            if en_yuksek_skor < SIMILARITY_THRESHOLD:
                print("\n=== AI ANSWER ===")
                print(FALLBACK_RESPONSE)
                print("-" * 55)
                print(f"🛡️  Guardrail Devreye Girdi (Max Benzerlik: {en_yuksek_skor:.3f} < {SIMILARITY_THRESHOLD})")
                print(f"⏱️  Metrikler | Arama: {retrieval_time:.3f}s | LLM Üretim: 0.00s | Toplam: {retrieval_time:.3f}s")
                print("-" * 55)
                continue

            # C) STRICT ZERO-INFERENCE PROMPT
            context_text = "\n\n".join(
                [
                    f"[Document Part {i+1}]: {p[1]}"
                    for i, p in enumerate(en_alakali_parcalar)
                ]
            )

            system_msg = (
                "You are an exact fact-extraction bot.\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. Answer ONLY using direct statements explicitly found in the Document Parts.\n"
                "2. Do NOT guess, do NOT assume, and do NOT make logical inferences.\n"
                "3. Append the citation tag (e.g. [Document Part 1]) to every factual claim.\n"
                f"4. If the exact answer is not explicitly written, output strictly: '{FALLBACK_RESPONSE}'"
            )

            user_msg = (
                f"Document Parts:\n{context_text}\n\n"
                f"Question: {soru}\n"
                f"Direct Answer (with [Document Part X]):"
            )

            # D) GENERATION & BENCHMARK
            t0_gen = time.time()
            response = client.complete_chat(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]
            )
            gen_time = time.time() - t0_gen
            answer_content = response.choices[0].message.content

            # E) DISPLAY OUTPUT & METRICS
            print("\n=== AI ANSWER ===")
            print(answer_content)
            print("-" * 55)
            print("Geri Getirilen Kaynak Parçaları:")
            for i, p in enumerate(en_alakali_parcalar):
                snippet = p[1][:90].replace("\n", " ") + "..."
                print(f"  • [Document Part {i+1}] (ID: {p[0]} | Benzerlik: {p[2]:.3f}): \"{snippet}\"")
            print("-" * 55)
            print(
                f"⏱️  Metrikler | Arama: {retrieval_time:.3f}s | LLM Üretim: {gen_time:.2f}s | Toplam: {retrieval_time + gen_time:.2f}s"
            )
            print("-" * 55)

        except Exception as e:
            print(f"❌ Bir hata oluştu: {e}")


if __name__ == "__main__":
    main()
