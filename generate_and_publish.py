import os
import json
import requests
import base64
from datetime import datetime
from pathlib import Path

# ── Config from env vars (GitHub Secrets) ──────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WP_URL            = os.environ["WP_URL"].rstrip("/")
WP_USER           = os.environ["WP_USER"]
WP_APP_PASSWORD   = os.environ["WP_APP_PASSWORD"]
PUBLISH_STATUS    = os.environ.get("PUBLISH_STATUS", "draft")

# ── Referral links from Secrets ────────────────────────────────────
REFERRAL_LINKS = {
    "Urbanitae":    os.environ.get("REF_URBANITAE",   "https://ladrillocolectivo.com/urbanitae-opinion/"),
    "WeCity":       os.environ.get("REF_WECITY",      "https://ladrillocolectivo.com/wecity-opinion/"),
    "Civislend":    os.environ.get("REF_CIVISLEND",   "https://ladrillocolectivo.com/civislend-opinion/"),
    "StockCrowd IN":os.environ.get("REF_STOCKCROWD",  "https://ladrillocolectivo.com/stockcrowd-in-opinion/"),
    "Mintos":       os.environ.get("REF_MINTOS",      "https://ladrillocolectivo.com/mintos-opinion/"),
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
        for t in data["topics"]:
            t["status"] = "pending"
        save_topics(data)
        pending = data["topics"]
    return data, pending[0]

def mark_done(data, topic_id):
    for t in data["topics"]:
        if t["id"] == topic_id:
            t["status"] = "done"
            t["published_at"] = datetime.utcnow().isoformat()
    save_topics(data)

# ── Get existing post titles from WP to avoid duplicates ───────────
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

# ── Claude API call ────────────────────────────────────────────────
def generate_article(topic: dict, existing_titles: list[str]) -> dict:
    year = datetime.utcnow().year
    referral_block = "\n".join(
        f'- {name}: {url}' for name, url in REFERRAL_LINKS.items()
    )
    existing_block = "\n".join(f"- {t}" for t in existing_titles[:30]) if existing_titles else "Ninguno aún."

    system_prompt = f"""Eres el redactor de ladrillocolectivo.com, un blog sobre crowdfunding inmobiliario en España.
El blog tiene este tagline: "La inflación se come tus ahorros. El ladrillo puede defenderlos."

TONO Y ESTILO (imita esto exactamente):
- Directo, práctico, tutea siempre al lector
- Frases cortas. Párrafos de máximo 3-4 líneas
- Abre con una pregunta retórica o un problema concreto del lector
- Usa **negrita** para conceptos clave
- Usa > blockquote para insights o tips importantes
- Incluye ejemplos reales y datos concretos cuando puedas
- Sin palabrería corporativa. Sin "en conclusión", "en resumen", "como hemos visto"
- CTA natural, no agresivo: invitar a registrarse como si fuera un consejo de amigo

REGLAS SEO (RankMath):
- La keyword principal debe aparecer en el primer párrafo, en al menos un H2, y en el último párrafo
- NO escribas el H1/título — WordPress lo pone solo. El contenido empieza directamente con el primer párrafo
- Meta descripción: máximo 155 caracteres, incluye la keyword, termina con CTA suave
- Slug: solo minúsculas, guiones, sin acentos ni ñ

AÑO ACTUAL: {year}. No uses años pasados en títulos ni contenido.

Responde ÚNICAMENTE con JSON válido, sin backticks ni texto extra."""

    user_prompt = f"""Escribe un artículo para ladrillocolectivo.com sobre: "{topic['title']}"

Keyword principal: {topic['keyword']}
Keywords secundarias: {', '.join(topic.get('secondary_keywords', []))}
Intención de búsqueda: {topic['intent']}

Links de referido disponibles (úsalos de forma natural, mínimo 2):
{referral_block}

Artículos ya publicados (NO repitas estos temas ni titles similares):
{existing_block}

Estructura del contenido HTML:
- Primer párrafo: gancho con problema/pregunta del lector
- 3-5 secciones con <h2>
- Usa <strong>, <blockquote>, listas <ul> donde aporten valor
- 2-3 links internos/referido integrados con naturalidad
- Último párrafo: CTA suave hacia registro

Devuelve SOLO este JSON (sin backticks):
{{
  "title": "Título SEO {year} — sin H1 duplicado, con keyword",
  "slug": "slug-sin-acentos-ni-enie",
  "content": "HTML completo SIN etiqueta h1 — empieza con <p>",
  "excerpt": "Meta descripción 155 chars máx con keyword y CTA",
  "focus_keyword": "{topic['keyword']}",
  "tags": ["tag1", "tag2", "tag3"]
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
def publish_to_wordpress(article: dict) -> str:
    credentials = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()

    # Set RankMath focus keyword via meta
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

    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
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

    print("Fetching existing post titles...")
    existing_titles = get_existing_titles()
    print(f"Found {len(existing_titles)} existing posts")

    data, topic = pick_topic()
    print(f"Topic: {topic['title']}")

    article = generate_article(topic, existing_titles)
    print(f"Generated: {article['title']}")

    url = publish_to_wordpress(article)
    print(f"Published ({PUBLISH_STATUS}): {url or 'check WP dashboard'}")

    mark_done(data, topic["id"])
    print("Done ✓")

if __name__ == "__main__":
    main()
