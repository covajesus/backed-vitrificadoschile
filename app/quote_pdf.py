"""Presupuesto PDF fidelidad al modelo aprobado (ReportLab Canvas)."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.colors import Color, black, white
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

PAGE_W, PAGE_H = letter  # 612 x 792 (modelo aprobado)
LEFT = 18.0
RIGHT = 594.0
CONTENT_W = RIGHT - LEFT

RED = Color(0.929, 0.090, 0.090)
GRAY_BAR = Color(0.93, 0.93, 0.93)

COMPANY_NAME_1 = "VITRIFICADOS CHILE COMPAÑIA"
COMPANY_NAME_2 = "LIMITADA"
COMPANY_GIRO_1 = "VENTA AL POR MENOR DE ARTICULOS DE FERRETERIA Y"
COMPANY_GIRO_2 = "MATERIALES DE CONSTRUCCION"
COMPANY_RUT = "77.176.777-K"
COMPANY_ADDRESS = "Santiago"
COMPANY_COMMUNE = "Santiago"
COMPANY_EMAIL = "info@vitrificadoschile.com"
COMPANY_PHONE = "+56 944283565"
COMPANY_BRAND = "Vitrificados Chile"
VALIDITY_DAYS = 10

# Columnas tabla (x derecho de cada borde vertical)
COL_X = (18.0, 70.0, 385.0, 437.0, 489.0, 541.0, 594.0)
TABLE_TOP = 232.0
TABLE_BOTTOM = 555.0
HEADER_H = 15.0
ROW_H = 15.0

TERMS_TITLE = "TÉRMINOS Y CONDICIONES"
DEFAULT_TERMS_ITEMS = (
    "Este presupuesto incluye 3 capas vitrificado base al agua marca alemana Berger-Seidle de secado rapido.",
    "No se realizan retiros de aserrin, excedentes de material ni escombros.",
    "Forma de pago: 50% al comenzar los trabajos y 50% en la aplicación de la segunda capa de vitrificado.",
    "EL RETAPE NO TIENE GARANTIA.",
    "Reparacion exclusiva con palmetas nuevas.",
    "La reparacion es solo una proyeccion se cobrara solo lo autorizado y ejecutado.",
    "Esta cotizacion solo incluye la restauracion del filete existente, no incluye reposicion.",
    "No se incluye mover vidrios, espejos, cuadros, copas ni objetos fragiles.",
)
DEFAULT_TERMS = "\n".join(f"• {item}" for item in DEFAULT_TERMS_ITEMS)

_FONTS_READY = False


def _register_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    regular = Path(r"C:\Windows\Fonts\arial.ttf")
    bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
    if regular.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont("QuoteSans", str(regular)))
        pdfmetrics.registerFont(TTFont("QuoteSans-Bold", str(bold)))
    else:
        # Fallback Helvetica (sin tildes)
        pdfmetrics.registerFont(TTFont("QuoteSans", str(regular))) if regular.is_file() else None
    _FONTS_READY = True


def font_name(bold: bool = False) -> str:
    _register_fonts()
    if "QuoteSans-Bold" in pdfmetrics.getRegisteredFontNames() and bold:
        return "QuoteSans-Bold"
    if "QuoteSans" in pdfmetrics.getRegisteredFontNames():
        return "QuoteSans-Bold" if bold and "QuoteSans-Bold" in pdfmetrics.getRegisteredFontNames() else "QuoteSans"
    return "Helvetica-Bold" if bold else "Helvetica"


def top_y(y_from_top: float) -> float:
    """Convierte Y del modelo (origen arriba) a baseline ReportLab (origen abajo)."""
    return PAGE_H - y_from_top


def money_clp(amount: int | Decimal) -> str:
    value = int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"${value:,.0f}".replace(",", ".")


def amount_clp(amount: int | Decimal) -> str:
    value = int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{value:,.0f}".replace(",", ".")


def format_qty(value: float | Decimal) -> str:
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f").rstrip("0").rstrip(".")


def short_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def text_width(text: str, size: float, bold: bool = False) -> float:
    return pdfmetrics.stringWidth(text, font_name(bold), size)


def fit_text(text: str, max_width: float, size: float, bold: bool = False) -> str:
    value = text or ""
    if text_width(value, size, bold) <= max_width:
        return value
    trimmed = value
    while trimmed and text_width(trimmed + "...", size, bold) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}..."


def wrap_text(text: str, max_width: float, size: float, bold: bool = False, max_lines: int = 4) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if text_width(candidate, size, bold) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(words) != " ".join(lines):
        lines[-1] = fit_text(lines[-1], max_width, size, bold)
    return lines


@lru_cache(maxsize=1)
def prepared_logo_path() -> Path | None:
    """Logo circular con fondo negro convertido a transparente (escribe en /tmp)."""
    source = Path(__file__).resolve().parent / "assets" / "logo_circular.png"
    if not source.is_file():
        bundled = Path(__file__).resolve().parent / "assets" / "logo.jpg"
        return bundled if bundled.is_file() else None

    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    width, height = image.size
    # Quitar fondo negro fuera del circulo
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if r < 25 and g < 25 and b < 25:
                pixels[x, y] = (0, 0, 0, 0)

    # Asegurar mascara circular suave
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    inset = 2
    draw.ellipse((inset, inset, width - inset, height - inset), fill=255)
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output.paste(image, mask=mask)

    target = Path(tempfile.gettempdir()) / "vitrificados_logo_circular_pdf.png"
    output.save(target, format="PNG")
    return target


def draw_centered(c: canvas.Canvas, text: str, x: float, width: float, y_top: float, size: float, *, bold: bool = False, color=black) -> None:
    c.setFillColor(color)
    c.setFont(font_name(bold), size)
    tw = text_width(text, size, bold)
    c.drawString(x + (width - tw) / 2, top_y(y_top), text)


def draw_right(c: canvas.Canvas, text: str, right: float, y_top: float, size: float, *, bold: bool = False, color=black) -> None:
    c.setFillColor(color)
    c.setFont(font_name(bold), size)
    tw = text_width(text, size, bold)
    c.drawString(right - tw, top_y(y_top), text)


def draw_header(c: canvas.Canvas) -> float:
    """Encabezado: logo | empresa | caja roja. Devuelve Y inferior (desde arriba)."""
    logo = prepared_logo_path()
    if logo is not None:
        # Modelo: bbox (43, 27)-(153, 137) => 110x110
        c.drawImage(str(logo), 43, top_y(137), width=110, height=110, mask="auto", preserveAspectRatio=True)

    mid_x, mid_w = 180.0, 210.0
    draw_centered(c, COMPANY_NAME_1, mid_x, mid_w, 41.4, 10, bold=True)
    draw_centered(c, COMPANY_NAME_2, mid_x, mid_w, 55.4, 10, bold=True)
    draw_centered(c, COMPANY_GIRO_1, mid_x, mid_w, 74.5, 6.1, bold=True)
    draw_centered(c, COMPANY_GIRO_2, mid_x, mid_w, 85.6, 6.5, bold=True)

    # Contacto: labels alineados, valores en x=287
    value_x = 287.0
    for label, value, y in (
        ("Dirección:", COMPANY_ADDRESS, 103.7),
        ("Comuna:", COMPANY_COMMUNE, 115.7),
        ("Correo:", COMPANY_EMAIL, 127.7),
        ("Teléfono:", COMPANY_PHONE, 139.7),
    ):
        c.setFillColor(black)
        c.setFont(font_name(True), 7)
        lw = text_width(label, 7, True)
        c.drawString(value_x - lw, top_y(y), label)
        c.setFont(font_name(False), 7)
        c.drawString(value_x + 2, top_y(y), value)

    # Caja roja (408,27)-(593,113)
    box_x, box_y_top, box_w, box_h = 408.0, 27.0, 185.0, 86.0
    c.setStrokeColor(RED)
    c.setLineWidth(1.8)
    c.rect(box_x, top_y(box_y_top + box_h), box_w, box_h, stroke=1, fill=0)
    draw_centered(c, f"R.U.T.: {COMPANY_RUT}", box_x, box_w, 47.4, 10, bold=True, color=RED)
    draw_centered(c, "PRESUPUESTO", box_x, box_w, 72.6, 11, bold=True, color=RED)
    # N.º se completa en generate con numero
    return 148.0


def draw_red_number(c: canvas.Canvas, number: str) -> None:
    box_x, box_w = 408.0, 185.0
    draw_centered(c, f"N.º {number}", box_x, box_w, 96.6, 11, bold=True, color=RED)
    draw_centered(c, COMPANY_BRAND, box_x, box_w, 127.7, 7, bold=True, color=RED)


def draw_receiver_field(
    c: canvas.Canvas,
    label: str,
    value: str,
    label_x: float,
    colon_x: float,
    value_x: float,
    y_top: float,
    value_max_w: float,
) -> None:
    c.setFillColor(black)
    c.setFont(font_name(True), 7)
    c.drawString(label_x, top_y(y_top), label)
    c.setFont(font_name(False), 7)
    c.drawString(colon_x, top_y(y_top), ":")
    c.drawString(value_x, top_y(y_top), fit_text(value or "-", value_max_w, 7, False))


def draw_receiver_data(
    c: canvas.Canvas,
    *,
    client_name: str,
    document_id: str,
    client_phone: str,
    issued: date,
    due: date,
) -> float:
    """Seccion Datos del Receptor. Devuelve Y inferior (desde arriba)."""
    top = 151.0
    bar_h = 16.0
    body_h = 65.0
    # barra titulo
    c.setFillColor(GRAY_BAR)
    c.setStrokeColor(black)
    c.setLineWidth(1.0)
    c.rect(LEFT, top_y(top + bar_h + body_h), CONTENT_W, bar_h + body_h, stroke=1, fill=0)
    c.rect(LEFT, top_y(top + bar_h), CONTENT_W, bar_h, stroke=0, fill=1)
    c.setStrokeColor(black)
    c.setLineWidth(0.6)
    c.line(LEFT, top_y(top + bar_h), RIGHT, top_y(top + bar_h))

    c.setFillColor(black)
    c.setFont(font_name(True), 8)
    c.drawString(22.0, top_y(163.9), "Datos del Receptor")

    # Campos con : alineados y valor con espacio (value_x = colon + 8)
    left_label, left_colon, left_value = 22.0, 78.0, 86.0
    right_label, right_colon, right_value = 360.0, 463.0, 471.0
    rows = (
        ("Señor(es)", client_name or "-", "Fecha Venc.", short_date(due), 179.7),
        ("RUT", document_id or "-", "Fecha emisión", short_date(issued), 191.7),
        ("Dirección", client_phone or "-", "Ciudad", COMPANY_ADDRESS, 203.7),
        ("Comuna", "-", "Forma de Pago", "Transferencia", 215.7),
        ("Giro", "-", "Condiciones Vta.", "No Aplica", 227.7),
    )
    for left_l, left_v, right_l, right_v, y in rows:
        draw_receiver_field(c, left_l, left_v, left_label, left_colon, left_value, y, 250)
        draw_receiver_field(c, right_l, right_v, right_label, right_colon, right_value, y, 110)

    return top + bar_h + body_h  # 232


def draw_products_table(
    c: canvas.Canvas,
    lines: list[tuple[str, str, float, int, int]],
    table_top: float = TABLE_TOP,
    table_bottom: float = TABLE_BOTTOM,
) -> float:
    """Tabla con espacio libre inferior (diseño aprobado). Sin lineas horizontales entre filas."""
    c.setStrokeColor(black)
    c.setLineWidth(1.0)
    height = table_bottom - table_top
    c.rect(LEFT, top_y(table_bottom), CONTENT_W, height, stroke=1, fill=0)

    # verticales
    c.setLineWidth(0.65)
    for x in COL_X[1:-1]:
        c.line(x, top_y(table_bottom), x, top_y(table_top))

    # encabezado
    headers = (
        (COL_X[0], COL_X[1], "CANTIDAD"),
        (COL_X[1], COL_X[2], "DESCRIPCIÓN"),
        (COL_X[2], COL_X[3], "PRECIO UNIT."),
        (COL_X[3], COL_X[4], "DESCUENTO"),
        (COL_X[4], COL_X[5], "RECARGO"),
        (COL_X[5], COL_X[6], "TOTAL ITEM"),
    )
    header_y = table_top + 11.0
    for x0, x1, title in headers:
        draw_centered(c, title, x0, x1 - x0, header_y, 5.8, bold=True)

    c.setLineWidth(0.85)
    c.line(LEFT, top_y(table_top + HEADER_H), RIGHT, top_y(table_top + HEADER_H))

    # filas (sin rayas horizontales)
    y = table_top + HEADER_H + 12.0
    max_y = table_bottom - 8.0
    for name, unit_label, quantity, unit_price, line_total in lines:
        if y > max_y:
            break
        description = name if not unit_label else f"{name} ({unit_label})"
        description = fit_text(description, COL_X[2] - COL_X[1] - 10, 7, True)
        c.setFillColor(black)
        c.setFont(font_name(True), 7)
        # cantidad cerca del borde derecho de col 0 / inicio desc (como modelo: qty en 62)
        qty = format_qty(quantity)
        c.drawString(62.1, top_y(y), qty)
        c.drawString(74.0, top_y(y), description)
        draw_right(c, amount_clp(unit_price), COL_X[3] - 4, y, 7, bold=True)
        draw_right(c, "-0", COL_X[4] - 4, y, 7, bold=True)
        draw_right(c, "0", COL_X[5] - 4, y, 7, bold=True)
        draw_right(c, amount_clp(line_total), COL_X[6] - 4, y, 7, bold=True)
        y += ROW_H

    return table_bottom


def _para_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def draw_totals(
    c: canvas.Canvas,
    *,
    terms: str,
    subtotal: int,
    tax: int,
    total: int,
) -> None:
    # Caja inferior: terminos justificados a la izquierda, totales a la derecha
    box_top, box_bottom = 568.0, 753.0
    c.setStrokeColor(black)
    c.setLineWidth(0.9)
    c.rect(LEFT, top_y(box_bottom), CONTENT_W, box_bottom - box_top, stroke=1, fill=0)
    c.setLineWidth(0.8)
    c.line(385.0, top_y(box_bottom), 385.0, top_y(box_top))

    raw = (terms or "").strip() or DEFAULT_TERMS
    upper = raw.upper().replace("É", "E")
    if upper.startswith("TERMINOS Y CONDICIONES"):
        parts = raw.split("\n", 1)
        raw = (parts[1] if len(parts) > 1 else "").strip() or DEFAULT_TERMS

    items: list[str] = []
    for part in raw.replace("\r\n", "\n").split("\n"):
        line = part.strip()
        if not line:
            continue
        for prefix in ("• ", "- ", "* ", "· "):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if line:
            items.append(line)
    if not items:
        items = list(DEFAULT_TERMS_ITEMS)

    title_style = ParagraphStyle(
        "QuoteTermsTitle",
        fontName=font_name(True),
        fontSize=11,
        leading=14,
        textColor=black,
        alignment=TA_LEFT,
    )
    body_style = ParagraphStyle(
        "QuoteTermsBody",
        fontName=font_name(False),
        fontSize=9,
        leading=11.5,
        textColor=black,
        alignment=TA_JUSTIFY,
        leftIndent=12,
        bulletIndent=0,
        bulletFontName=font_name(False),
        bulletFontSize=9,
    )

    terms_width = 348.0
    cursor_top = 580.0
    title_para = Paragraph(_para_escape(TERMS_TITLE), title_style)
    title_w, title_h = title_para.wrap(terms_width, 40)
    title_para.drawOn(c, 26.0, top_y(cursor_top) - title_h + 11)
    cursor_top += title_h + 5

    for item in items:
        if cursor_top > 748:
            break
        # Viñeta + texto justificado por cada punto
        bullet_html = f"• {_para_escape(item)}"
        item_para = Paragraph(bullet_html, body_style)
        max_h = max(16.0, 750.0 - cursor_top)
        _w, item_h = item_para.wrap(terms_width, max_h)
        item_para.drawOn(c, 26.0, top_y(cursor_top) - item_h + 9)
        cursor_top += item_h + 3.5

    rows = (
        ("SUBTOTAL", "(=)", money_clp(subtotal), 640.0),
        ("NETO", "(=)", money_clp(subtotal), 662.0),
        ("IVA (19%)", "(+)", money_clp(tax), 684.0),
        ("EXENTO", "(+)", money_clp(0), 706.0),
        ("TOTAL", "(=)", money_clp(total), 732.0),
    )
    for label, op, value, y in rows:
        c.setFont(font_name(True), 7.5)
        c.setFillColor(black)
        c.drawString(392.0, top_y(y), label)
        c.setFont(font_name(True), 7)
        c.drawString(508.9, top_y(y), op)
        draw_right(c, value, 587.0, y, 7.5, bold=True)


def draw_footer(c: canvas.Canvas, page: int, pages: int) -> None:
    c.setFillColor(black)
    c.setFont(font_name(False), 6)
    c.drawString(LEFT, top_y(768.4), "Documento generado para Vitrificados Chile")
    label = f"Página {page} de {pages}"
    draw_right(c, label, RIGHT, 768.4, 6, bold=False)


def paginate_lines(lines: list[tuple[str, str, float, int, int]]) -> list[list[tuple[str, str, float, int, int]]]:
    usable = TABLE_BOTTOM - TABLE_TOP - HEADER_H - 16
    capacity = max(1, int(usable // ROW_H))
    if not lines:
        return [[]]
    return [lines[i:i + capacity] for i in range(0, len(lines), capacity)]


def generate_budget_pdf(
    *,
    number: str,
    document_id: str,
    client_name: str,
    client_phone: str,
    notes: str,
    lines: list[tuple[str, str, float, int, int]],
    subtotal: int,
    tax: int,
    total: int,
    issued_at: datetime | None = None,
) -> bytes:
    issued = (issued_at or datetime.utcnow()).date()
    due = issued + timedelta(days=VALIDITY_DAYS)
    chunks = paginate_lines(lines)
    pages = len(chunks)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setTitle(f"Presupuesto {number}")

    for index, page_lines in enumerate(chunks, start=1):
        draw_header(c)
        draw_red_number(c, number)
        draw_receiver_data(
            c,
            client_name=client_name,
            document_id=document_id,
            client_phone=client_phone,
            issued=issued,
            due=due,
        )
        draw_products_table(c, page_lines)
        if index == pages:
            draw_totals(c, terms=notes, subtotal=subtotal, tax=tax, total=total)
        draw_footer(c, index, pages)
        c.showPage()

    c.save()
    return buffer.getvalue()


def quote_pdf(
    *,
    number: str,
    document_id: str,
    client_name: str,
    client_phone: str,
    notes: str,
    lines: list[tuple[str, str, float, int, int]],
    subtotal: int,
    tax: int,
    total: int,
    issued_at: datetime | None = None,
) -> bytes:
    """Compatibilidad con el endpoint existente."""
    return generate_budget_pdf(
        number=number,
        document_id=document_id,
        client_name=client_name,
        client_phone=client_phone,
        notes=notes,
        lines=lines,
        subtotal=subtotal,
        tax=tax,
        total=total,
        issued_at=issued_at,
    )
