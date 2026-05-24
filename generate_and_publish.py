import os
import json
import random
import requests
import base64
from datetime import datetime
from pathlib import Path

# ── Config from env vars (GitHub Secrets) ──────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WP_URL            = os.environ["WP_URL"].rstrip("/")
WP_USER           = os.environ["WP_USER"]
WP_APP_PASSWORD   = os.environ["WP_APP_PASSWORD"]
PUBLISH_STATUS    = os.environ.get("PUBLISH_STATUS", "draft")  # draft | publish

# ── Referral links — edit these ────────────────────────────────────
REFERRAL_LINKS = {
    "urbanitae":   "https://urbanitae.com/?ref=TU_CODIGO",
    "wecity":      "https://wecity.es/?ref=TU_CODIGO",
    "civislend":   "https://civislend.com/?ref=TU_CODIGO",
    "stockcrowd":  "https://stockcrowdin.com/?ref=TU_CODIGO",
    "housers":     "https://housers.com/?ref=TU_CODIGO",
}

# ── Topic queue ────────────────────────────────────────────────────
TOPICS_FILE = Path(__file__).parent / "topics" / "queue.json"

def load_topics():
    with open(TOPICS_FILE) as f:
        return json.load(f)

def save_topics(data):
    with open(TOPICS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def pick_topic():
    data = load_topics()
    pending = [t for t in data["topics"] if t["status"] == "pending"]
    if not pending:
        # Reset all to pending when queue is exhausted
        for t in data["topics"]:
            t["status"] = "pending"
        save_topics(data)
        pending = data["topics"]
    topic = pending[0]
    return data, topic

def mark_done(data, topic_id):
    for t in data["topics"]:
        if t["id"] == topic_id:
            t["status"] = "done"
            t["published_at"] = datetime.utcnow().isoformat()
    save_topics(data)

# ── Claude API call ────────────────────────────────────────────────
def generate_article(topic: dict) -> dict:
    referral_block = "\n".join(
        f'- {name.capitalize()}: {url}' for name, url in REFERRAL_LINKS.items()
    )

    system_prompt = """Eres un experto en crowdfunding inmobiliario en España con tono cercano, 
honesto y orientado al lector que quiere empezar a invertir. 
Escribes para ladrillocolectivo.com, un blog de referencia sobre inversión inmobiliaria colectiva.
Tu objetivo es que el lector haga clic en los enlaces de registro de las plataformas recomendadas.
Responde ÚNICAMENTE con un objeto JSON válido, sin backticks ni texto extra."""

    user_prompt = f"""Escribe un artículo SEO completo en español sobre: "{topic['title']}"

Keyword principal: {topic['keyword']}
Keywords secundarias: {', '.join(topic.get('secondary_keywords', []))}
Intención de búsqueda: {topic['intent']}

Estructura requerida:
- Introducción con gancho (el problema o pregunta del lector)
- 3-5 secciones con H2
- Al menos 2 menciones naturales de plataformas con enlaces de referido
- CTA final claro invitando al registro
- Longitud: 900-1200 palabras

Links de referido disponibles:
{referral_block}

Devuelve SOLO este JSON:
{{
  "title": "título SEO optimizado",
  "slug": "slug-url-amigable",
  "content": "contenido HTML completo con etiquetas <h2>, <p>, <a href='...'>, <strong>",
  "excerpt": "meta descripción de 150 caracteres máximo",
  "tags": ["tag1", "tag2", "tag3"],
  "focus_keyword": "{topic['keyword']}"
}}"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()["content"][0]["text"]

    # Strip potential markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ── WordPress publish ──────────────────────────────────────────────
def publish_to_wordpress(article: dict) -> str:
    credentials = base64.b64encode(
        f"{WP_USER}:{WP_APP_PASSWORD}".encode()
    ).decode("utf-8")

    payload = {
        "title":   article["title"],
        "content": article["content"],
        "excerpt": article.get("excerpt", ""),
        "slug":    article.get("slug", ""),
        "status":  PUBLISH_STATUS,
        "tags":    [],  # Could resolve tag IDs here if needed
    }

    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    print("WP response:", r.status_code, r.text[:500])
    r.raise_for_status()
    return r.json().get("link", "")

# ── Main ───────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting article generation...")

    data, topic = pick_topic()
    print(f"Topic selected: {topic['title']}")

    article = generate_article(topic)
    print(f"Article generated: {article['title']}")

    url = publish_to_wordpress(article)
    print(f"Published ({PUBLISH_STATUS}): {url or 'check WP dashboard'}")

    mark_done(data, topic["id"])
    print("Topic marked as done. ✓")

if __name__ == "__main__":
    main()
