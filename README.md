# wp-autopublish

Genera y publica artículos SEO automáticamente en WordPress usando Claude API.  
Diseñado para **ladrillocolectivo.com** — crowdfunding inmobiliario con links de referido.

## Setup (10 minutos)

### 1. Sube este repo a GitHub

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/TU_USUARIO/wp-autopublish.git
git push -u origin main
```

### 2. Añade los secretos en GitHub

Ve a tu repo → **Settings → Secrets and variables → Actions → New repository secret**

| Nombre | Valor |
|--------|-------|
| `ANTHROPIC_API_KEY` | Tu API key de console.anthropic.com |
| `WP_URL` | `https://ladrillocolectivo.com` |
| `WP_USER` | Tu usuario administrador de WP |
| `WP_APP_PASSWORD` | La contraseña de aplicación generada en WP |

### 3. Añade tus links de referido

Edita `generate_and_publish.py` → sección `REFERRAL_LINKS` → reemplaza `TU_CODIGO` con tus códigos reales.

### 4. Prueba manual

Ve a **Actions → Publish Article to WordPress → Run workflow**  
Comprueba tu WP dashboard → debería aparecer un borrador nuevo.

---

## Frecuencia

Por defecto: **lunes y jueves a las 9:00h** (hora Madrid).  
Para cambiar la frecuencia, edita el cron en `.github/workflows/publish.yml`.

Ejemplos:
- Diario a las 9h: `0 7 * * *`
- Solo lunes: `0 7 * * 1`
- 3 veces/semana: `0 7 * * 1,3,5`

## Cola de artículos

Los temas están en `topics/queue.json`.  
El script los publica en orden y marca cada uno como `done`.  
Cuando se agotan todos, reinicia la cola automáticamente.

Para añadir temas nuevos: edita el JSON añadiendo objetos con `"status": "pending"`.

## Cambiar de borrador a publicación directa

En `.github/workflows/publish.yml`, cambia:
```yaml
PUBLISH_STATUS: draft
```
por:
```yaml
PUBLISH_STATUS: publish
```
