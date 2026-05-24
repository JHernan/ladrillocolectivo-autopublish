import os
import json
import requests
import base64
from datetime import datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WP_URL            = os.environ["WP_URL"].rstrip("/")
WP_USER           = os.environ["WP_USER"]
WP_APP_PASSWORD   = os.environ["WP_APP_PASSWORD"]
PEXELS_API_KEY    = os.environ.get("PEXELS_API_KEY", "")
PUBLISH_STATUS    = os.environ.get("PUBLISH_STATUS", "draft")

# ── Referral links (internal pages) ────────────────────────────────
REFERRAL_LINKS = {
    "Urbanitae":     "https://ladrillocolectivo.com/urbanitae-opinion/",
    "WeCity":        "https://ladrillocolectivo.com/wecity-opinion/",
    "Civislend":     "https://ladrillocolectivo.com/civislend-opinion/",
    "StockCrowd IN": "https://ladrillocolectivo.com/stockcrowd-in-opinion/",
    "Mintos":        "https://ladrillocolectivo.com/mintos-opinion/",
}

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
        for t in data["topics"]:
            t["status"] = "pending"
        save_topics(data)
        pending = [t for t in data["topics"] if t["id"] != 1]  # never reuse topic 1
    return data, pending[0]

def mark_done(data, topic_id):
    for t in data["topics"]:
        if t["id"] == topic_id:
            t["status"] = "done"
            t["published_at"] = datetime.utcnow().isoformat()
    save_topics(data)

# ── Get existing content from WP ───────────────────────────────────
def get_existing_titles() -> list[str]:
    credentials = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    titles = []
    page = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers={"Authorization": f"Basic {credentials}"},
            params={"per_page": 100, "page": page, "status": "any", "_fields": "title"},
            timeout=30,
        )
        if r.status_code != 200 or not r.json():
            break
        titles += [p["title"]["rendered"] for p in r.json()]
        if len(r.json()) < 100:
            break
        page += 1
    return titles

def get_home_excerpt() -> str:
    """Fetch home page text to avoid duplicating its content."""
    try:
        r = requests.get(WP_URL, timeout=15)
        # Return first 800 chars of visible text as context
        import re
        text = re.sub(r'<[^>]+>', ' ', r.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:800]
    except Exception:
        return ""

# ── Pexels image ───────────────────────────────────────────────────
def fetch_pexels_image(query: str) -> dict | None:
    if not PEXELS_API_KEY:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            timeout=15,
        )
        photos = r.json().get("photos", [])
        if not photos:
            return None
        photo = photos[0]
        return {
            "url":          photo["src"]["large2x"],
            "photographer": photo["photographer"],
            "pexels_url":   photo["url"],
        }
    except Exception as e:
        print(f"Pexels error: {e}")
        return None

def upload_image_to_wp(image_url: str, filename: str, alt_text: str) -> int | None:
    """Download image and upload to WP media library. Returns media ID."""
    try:
        img_data = requests.get(image_url, timeout=30).content
        credentials = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers={
                "Authorization":       f"Basic {credentials}",
                "Content-Disposition": f'attachment; filename="{filename}.jpg"',
                "Content-Type":        "image/jpeg",
            },
            data=img_data,
            timeout=60,
        )
        if r.status_code in (200, 201):
            media_id = r.json().get("id")
            # Set alt text
            requests.post(
                f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type":  "application/json",
                },
                json={"alt_text": alt_text},
                timeout=15,
            )
            return media_id
    except Exception as e:
        print(f"Image upload error: {e}")
    return None

# ── Claude article generation ───────────────────────────────────────
def generate_article(topic: dict, existing_titles: list[str], home_excerpt: str) -> dict:
    year = datetime.utcnow().year
    referral_block = "\n".join(f'- {name}: {url}' for name, url in REFERRAL_LINKS.items())
    existing_block = "\n".join(f"- {t}" for t in existing_titles[:40]) if existing_titles else "Ninguno."

    system_prompt = f"""Eres el redactor de ladrillocolectivo.com, blog de crowdfunding inmobiliario en España.
Tagline del blog: "La inflación se come tus ahorros. El ladrillo puede defenderlos."

TONO Y ESTILO:
- Directo, práctico, tutea al lector
- Frases cortas. Párrafos de máximo 3-4 líneas
- Abre con una pregunta retórica o un problema concreto del lector
- Usa <strong> para conceptos clave
- Usa <blockquote> para insights o tips importantes
- Datos concretos y ejemplos reales cuando sea posible
- Sin "en conclusión", "en resumen", "como hemos visto"
- CTA final natural: consejo de amigo, no vendedor

SEO (RankMath):
- Keyword principal en: primer párrafo, al menos un H2, último párrafo
- NO incluyas etiqueta <h1> — WordPress la pone automáticamente
- El contenido empieza directamente con <p>
- Meta descripción: máx 155 caracteres, incluye keyword, acaba con CTA suave
- Slug: minúsculas, guiones, sin acentos ni ñ

AÑO: {year}

Responde ÚNICAMENTE con JSON válido, sin backticks."""

    user_prompt = f"""Artículo para ladrillocolectivo.com: "{topic['title']}"

Keyword principal: {topic['keyword']}
Keywords secundarias: {', '.join(topic.get('secondary_keywords', []))}
Intención: {topic['intent']}

Links internos disponibles (usa mínimo 2 de forma natural):
{referral_block}

CONTENIDO YA PUBLICADO — no repitas ni solapas con esto:
Home del blog: {home_excerpt}

Títulos ya publicados:
{existing_block}

Estructura HTML requerida:
- <p> de gancho (problema/pregunta del lector)
- 3-5 secciones <h2>
- <strong>, <blockquote>, <ul> donde aporten valor
- 2-3 links internos integrados con naturalidad
- Último <p>: CTA suave hacia registro

JSON de respuesta (sin backticks):
{{
  "title": "Título SEO {year} con keyword — sin duplicar home ni posts existentes",
  "slug": "slug-sin-acentos-ni-enie",
  "content": "HTML completo empezando con <p>, sin <h1>",
  "excerpt": "Meta descripción máx 155 chars con keyword y CTA",
  "focus_keyword": "{topic['keyword']}",
  "image_search_query": "3-4 palabras en inglés para buscar imagen en Pexels"
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
    raw = response.json()["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ── WordPress publish ──────────────────────────────────────────────
def publish_to_wordpress(article: dict, featured_image_id: int | None) -> str:
    credentials = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()

    payload = {
        "title":   article["title"],
        "content": article["content"],
        "excerpt": article.get("excerpt", ""),
        "slug":    article.get("slug", ""),
        "status":  PUBLISH_STATUS,
        "meta": {
            "rank_math_focus_keyword": article.get("focus_keyword", ""),
            "rank_math_description":   article.get("excerpt", ""),
        },
    }
    if featured_image_id:
        payload["featured_media"] = featured_image_id

    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/json",
        },
        json=payload,
        timeout=30,
    )
    print("WP response:", r.status_code, r.text[:300])
    r.raise_for_status()
    return r.json().get("link", "")

# ── Main ───────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting...")

    existing_titles = get_existing_titles()
    print(f"Existing posts: {len(existing_titles)}")

    home_excerpt = get_home_excerpt()
    print("Home page fetched for context")

    data, topic = pick_topic()
    print(f"Topic: {topic['title']}")

    article = generate_article(topic, existing_titles, home_excerpt)
    print(f"Generated: {article['title']}")

    # Featured image via Pexels
    featured_image_id = None
    if PEXELS_API_KEY:
        query = article.get("image_search_query", "real estate investment spain")
        print(f"Fetching image: {query}")
        image = fetch_pexels_image(query)
        if image:
            featured_image_id = upload_image_to_wp(
                image["url"],
                article.get("slug", "article"),
                article["title"],
            )
            print(f"Image uploaded, ID: {featured_image_id}")
    else:
        print("No PEXELS_API_KEY — skipping featured image")

    url = publish_to_wordpress(article, featured_image_id)
    print(f"Published ({PUBLISH_STATUS}): {url or 'check WP dashboard'}")

    mark_done(data, topic["id"])
    print("Done ✓")

if __name__ == "__main__":
    main()
