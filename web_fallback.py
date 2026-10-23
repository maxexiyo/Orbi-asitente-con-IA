"""Respaldo de búsqueda web SIN API de Gemini: DuckDuckGo (versión HTML, sin key ni cuota).
Se usa cuando investigar_web no puede con Gemini (modelo inexistente, cuota agotada, lento)."""
import html as _html
import re
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def _limpia(s: str) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def parse_ddg_html(page: str, n: int = 5) -> list:
    """-> [{titulo, resumen, url, dominio}] a partir del HTML de html.duckduckgo.com"""
    out = []
    for block in re.split(r'<div[^>]+class="[^"]*\bresult\b[^"]*"[^>]*>', page)[1:]:
        tag = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>', block)
        if not tag:
            continue
        titulo = _limpia((re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', block, re.S) or [None, ""])[1])
        href = (re.search(r'href="([^"]+)"', tag.group(0)) or [None, ""])[1]
        href = _html.unescape(href)
        if href.startswith("//"):
            href = "https:" + href
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        url = q["uddg"][0] if q.get("uddg") else href
        sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.S)
        dominio = urllib.parse.urlparse(url).netloc.replace("www.", "")
        if titulo and url.startswith("http"):
            out.append({"titulo": titulo[:120], "resumen": _limpia(sn.group(1))[:300] if sn else "",
                        "url": url, "dominio": dominio})
        if len(out) >= n:
            break
    return out


def ddg_search(consulta: str, timeout: float = 5.0, n: int = 5) -> list:
    data = urllib.parse.urlencode({"q": consulta, "kl": "mx-es"}).encode()
    req = urllib.request.Request("https://html.duckduckgo.com/html/", data=data,
                                 headers={"User-Agent": UA, "Accept-Language": "es-MX,es;q=0.9,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        page = r.read(600_000).decode("utf-8", "replace")
    return parse_ddg_html(page, n)
