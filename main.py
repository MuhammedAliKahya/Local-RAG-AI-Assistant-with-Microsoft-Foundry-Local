"""
====================================================================
PROJE: Offline Local RAG (Retrieval-Augmented Generation) AI Assistant
ALTYAPI: Microsoft Foundry Local + Qwen 2.5 (0.5B) + BGE Embeddings + SQLite
MÜFREDAT: 6-Week Local AI Masterclass Final Production Code
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


# ====================================================================
# 1. STEP: DATA INGESTION & PIPELINE SETUP
# ====================================================================
def initialize_database():
    """PDF dökümanını okur, gürültüyü temizler, vektörleştirir ve SQLite veritabanını günceller."""
    print("📥 [1/4] PDF dökümanı taranıyor ve metin dilimleniyor...")

    if not os.path.exists(PDF_PATH):
        print(
            f"❌ Hata: '{PDF_PATH}' dosyası bulunamadı! Lütfen klasöre ekleyin."
        )
        exit(1)

    loader = PyPDFLoader(PDF_PATH)
    documents = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = text_splitter.split_documents(documents)

    # Gürültü ve kaynakça filtreleme
    filtered_chunks = []
    for c in chunks:
        content = c.page_content.strip()
        if "https://doi.org" in content and "Dergisi" in content:
            continue
        if content.startswith("References") or content.startswith("KAYNAKÇA"):
            continue
        filtered_chunks.append(content)

    print(f"--> {len(filtered_chunks)} adet optimize edilmiş metin parçası hazır.")

    print(
        f"🧠 [2/4] BGE Vektör Modeli ({EMBEDDING_MODEL_NAME}) yükleniyor..."
    )
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
    print("--> Vektör veritabanı başarıyla senkronize edildi!\n")
    return embed_model


# ====================================================================
# 2. STEP: VECTOR RETRIEVAL ENGINE
# ====================================================================
def search_similar_chunks(query, embed_model, top_k=TOP_K_RESULTS):
    """Kullanıcı sorusunu vektörleştirir ve Kosinüs Benzerliği ile veritabanında arar."""
    clean_query = query.strip().strip('"').strip("'")
    query_vector = embed_model.encode(clean_query, normalize_embeddings=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT content, embedding FROM documents")
    rows = cursor.fetchall()
    conn.close()

    results = []
    for content, vector_str in rows:
        doc_vector = np.array(json.loads(vector_str))
        sim_score = np.dot(query_vector, doc_vector)  # Skaler Çarpım
        results.append((content, sim_score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


# ====================================================================
# 3. STEP: MAIN APPLICATION & SYSTEM EXECUTION
# ====================================================================
def main():
    # Veritabanını ve Vektör Modelini Hazırla
    embed_model = initialize_database()

    # Foundry Local Runtime ve Qwen 2.5 Modeli Başlatma
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
    print("Sıfır İnternet Bağlantısı | Tam Yerel Çalışma | Sıfır Halüsinasyon")
    print("=" * 65 + "\n")

    while True:
        try:
            soru = input("\nSoru girin (Çıkış için 'q'): ")
            if soru.lower() in ["çıkış", "exit", "q"]:
                print("RAG Asistanı kapatılıyor. Love you <3")
                break

            if not soru.strip():
                continue

            # A) RETRIEVAL & BENCHMARK
            t0_retrieval = time.time()
            en_alakali_parcalar = search_similar_chunks(soru, embed_model)
            retrieval_time = time.time() - t0_retrieval

            # Context Bağlamını Oluşturma
            context_text = "\n\n".join(
                [
                    f"[Document Part {i+1}]: {p[0]}"
                    for i, p in enumerate(en_alakali_parcalar)
                ]
            )

            # B) STRICT GUARDRAIL SYSTEM PROMPT
            system_msg = (
                "You are a strict academic Q&A assistant. "
                "Answer the question using ONLY the facts explicitly provided in the Document Parts. "
                "If the answer is found, provide a concise answer AND explicitly cite which Document Part you used (e.g., [Document Part 1]). "
                "If the answer is NOT present in the text, respond exactly: "
                "'The provided document context does not contain information to answer this question.'"
            )

            user_msg = (
                f"Document Parts:\n{context_text}\n\nQuestion: {soru}\nAnswer:"
            )

            # C) GENERATION & BENCHMARK
            t0_gen = time.time()
            response = client.complete_chat(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]
            )
            gen_time = time.time() - t0_gen

            # D) DISPLAY OUTPUT & METRICS
            print("\n=== AI ANSWER ===")
            print(response.choices[0].message.content)
            print("-" * 50)
            print(
                f"⏱️  Metrikler | Arama: {retrieval_time:.3f}s | LLM Üretim: {gen_time:.2f}s | Toplam: {retrieval_time + gen_time:.2f}s"
            )
            print("-" * 50)

        except Exception as e:
            print(f"❌ Bir hata oluştu: {e}")


if __name__ == "__main__":
    main()