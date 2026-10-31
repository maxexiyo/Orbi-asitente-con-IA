"""Responder un correo CONSERVANDO el hilo (Gmail por IMAP/SMTP y Microsoft por Graph), usando el hub de cuentas de Orbi.

  preparar(hub, id)                      -> dict con a quién se responde, asunto «Re: …», cabeceras del hilo y el texto citado
  enviar(hub, prep, para, asunto, texto) -> envía la respuesta (Gmail: con In-Reply-To/References; Microsoft: endpoint de «responder»)

La vista previa y el OK del usuario los pone pc_tools (igual que al enviar un correo nuevo). El contenido del correo original es DATO.
"""
import email
import re
import smtplib
import urllib.parse
from email.mime.text import MIMEText
from email.utils import parseaddr

import correo_cuentas as cc

NO_RESPONDER = re.compile(r"(no[-_.]?reply|noreply|do[-_.]?not[-_.]?reply|mailer-daemon|notifications?@)", re.I)


def _cita(de: str, fecha: str, texto: str) -> str:
    lineas = [ln.rstrip() for ln in str(texto or "").splitlines() if ln.strip()][:14]
    if not lineas:
        return ""
    return f"\n\nEl {fecha or 'día'}, {de} escribió:\n" + "\n".join("> " + ln for ln in lineas)


def preparar(hub, mid: str) -> dict:
    a, ref = hub._por_id(mid)
    if a["proveedor"] == "gmail":
        if not ref.isdigit():
            raise cc.MailError("id de correo inválido.")
        m = hub._imap(a)
        try:
            _, d = m.uid("FETCH", ref, "(BODY.PEEK[])")
            msg = email.message_from_bytes(d[0][1])
        finally:
            hub._bye(m)
        nombre, addr = parseaddr(msg["Reply-To"] or msg["From"] or "")
        de = cc._dec(msg["From"])[:80]
        asunto = cc._dec(msg["Subject"]).strip()
        mid_orig = (msg["Message-ID"] or "").strip()
        refs = ((msg["References"] or "").strip() + " " + mid_orig).strip()
        cita = _cita(de, (msg["Date"] or "")[:25], cc._body(msg))
    else:
        g = hub._graph(a, "GET", f"/me/messages/{urllib.parse.quote(hub._real(a, ref), safe='')}?$select=subject,from,replyTo",
                       headers={"Prefer": 'outlook.body-content-type="text"'})
        ea = (((g.get("replyTo") or [{}])[0]).get("emailAddress")) or (g.get("from") or {}).get("emailAddress") or {}
        addr, de = str(ea.get("address") or ""), str(ea.get("name") or ea.get("address") or "")
        asunto, mid_orig, refs, cita = str(g.get("subject") or "").strip(), "", "", ""
    if not addr or NO_RESPONDER.search(addr):
        raise cc.MailError(f"Ese correo es de una cuenta automática ({addr or 'sin remitente'}) que no recibe respuestas.")
    return dict(a=a, ref=ref, mid=mid, para=addr, de=de, desde=a["email"],
                asunto=asunto if re.match(r"(?i)^\s*(re|rv)\s*:", asunto) else f"Re: {asunto}".strip(),
                in_reply_to=mid_orig, references=refs, cita=cita, graph=(a["proveedor"] != "gmail"))


def enviar(hub, prep: dict, para: str, asunto: str, texto: str) -> dict:
    a = prep["a"]
    para = str(para or "").strip()
    if not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", para):
        return {"error": "Necesito UN correo destino válido."}
    if prep["graph"]:
        if para.lower() == prep["para"].lower():
            hub._graph(a, "POST", f"/me/messages/{urllib.parse.quote(hub._real(a, prep['ref']), safe='')}/reply", {"comment": str(texto)})
            return {"resultado": f"Respuesta enviada a {para} desde {a['email']}."}
        return hub.send(para, asunto, texto, a["alias"])               # cambió el destinatario: ya no es una respuesta, va como correo nuevo
    msg = MIMEText(str(texto), "plain", "utf-8")
    msg["From"], msg["To"], msg["Subject"] = a["email"], para, str(asunto)[:200]
    if prep.get("in_reply_to"):
        msg["In-Reply-To"] = prep["in_reply_to"]
        msg["References"] = prep["references"]
    with smtplib.SMTP_SSL(cc.GMAIL_SMTP, 465, timeout=15) as s:
        s.login(a["email"], a["clave"])
        s.send_message(msg)
    try:
        hub.mark_read(prep["mid"])                                     # al contestarlo, ya no cuenta como sin leer
    except Exception:                                                  # noqa: BLE001
        pass
    return {"resultado": f"Respuesta enviada a {para} desde {a['email']}."}
