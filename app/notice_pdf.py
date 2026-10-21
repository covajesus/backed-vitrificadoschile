import base64
import os
import tempfile
from datetime import date
from pathlib import Path

from fpdf import FPDF

from app.domain import palmeta_amount

MONTHS = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)


def logo_path() -> Path | None:
    bundled = Path(__file__).resolve().parent / "assets" / "logo.jpg"
    if bundled.is_file():
        return bundled
    root = Path(__file__).resolve().parents[2]
    for relative in (
        Path("frontend") / "src" / "assets" / "logo.png",
        Path("frontend") / "src" / "assets" / "logo-mark.png",
    ):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def money(amount: int) -> str:
    return f"${amount:,.0f}".replace(",", ".")


WEEK_DAYS = (
    (1, "Lun"),
    (2, "Mar"),
    (3, "Mié"),
    (4, "Jue"),
    (5, "Vie"),
    (6, "Sáb"),
    (0, "Dom"),
)
DAY_MODES = {
    "weekdays": [1, 2, 3, 4, 5],
    "weekend": [6, 0],
    "all": [1, 2, 3, 4, 5, 6, 0],
    "except-sunday": [1, 2, 3, 4, 5, 6],
}


def pdf_text(value: str) -> str:
    return value.encode("latin-1", "replace").decode("latin-1")


def write_line(pdf: FPDF, text: str, height: float = 8, bold: bool = False, size: int = 11) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, height, pdf_text(text))


def work_day_label(value: str) -> str:
    chosen = DAY_MODES.get(value)
    if chosen is None:
        chosen = []
        for part in value.split(","):
            if part.isdigit() and int(part) in {0, 1, 2, 3, 4, 5, 6}:
                chosen.append(int(part))
    return ", ".join(label for day, label in WEEK_DAYS if day in chosen)


def period_label(period: str) -> str:
    year, month = period.split("-")
    index = int(month) - 1
    if 0 <= index < len(MONTHS):
        return f"{MONTHS[index]} de {year}"
    return period


def embed_receipt(pdf: FPDF, receipt: str) -> None:
    if not receipt.startswith("data:image/"):
        return
    header, _, encoded = receipt.partition(",")
    if not encoded:
        return
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return
    suffix = ".png" if "png" in header else ".jpg"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(raw)
        handle.close()
        pdf.ln(4)
        write_line(pdf, "Comprobante de transferencia", bold=True)
        pdf.image(handle.name, w=90)
    except Exception:
        return
    finally:
        try:
            os.remove(handle.name)
        except OSError:
            pass


def settlement_pdf(
    *,
    person: str,
    period: str,
    items: list[tuple[str, int]],
    total: int,
    receipt: str,
) -> bytes:
    pdf = FPDF()
    pdf.set_compression(False)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    mark = logo_path()
    if mark is not None:
        try:
            pdf.image(str(mark), x=18, y=12, w=60)
            pdf.set_y(32)
        except Exception:
            pdf.set_y(16)
    else:
        pdf.set_y(16)
    write_line(pdf, "Liquidación de sueldo", bold=True, size=16)
    write_line(pdf, f"Trabajador: {person}")
    write_line(pdf, f"Periodo: {period_label(period)}")
    haberes = [(label, amount) for label, amount in items if amount >= 0]
    deductions = [(label, amount) for label, amount in items if amount < 0]
    write_line(pdf, "Haberes", bold=True)
    if not haberes:
        write_line(pdf, "Sin haberes en el periodo.")
    for label, amount in haberes:
        write_line(pdf, f"{label}    {money(amount)}")
    if deductions:
        pdf.set_text_color(225, 29, 72)
        write_line(pdf, "Deducciones", bold=True)
        for label, amount in deductions:
            write_line(pdf, f"{label}    -{money(abs(amount))}")
        pdf.set_text_color(0, 0, 0)
    else:
        write_line(pdf, "Sin deducciones.")
    write_line(pdf, f"Total a pagar: {money(total)}", bold=True)
    embed_receipt(pdf, receipt)
    return bytes(pdf.output())


def issue_date() -> str:
    today = date.today()
    return f"{today.day} de {MONTHS[today.month - 1]} de {today.year}"


def html_text(value: str) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def acceptance_clause(*, updated: bool) -> str:
    if updated:
        return (
            "<b>Quinto: Aceptación de la actualización.</b> Si los trabajos <b>vuelven a iniciarse</b>, "
            "esta actualización se tiene por <b>aceptada automáticamente</b>. Las partidas y cantidades "
            "aquí indicadas reemplazan a las pactadas con anterioridad y pasan a ser las únicas exigibles "
            "entre las partes."
        )
    return (
        "<b>Quinto: Aceptación.</b> El <b>inicio de los trabajos</b> en el inmueble importa "
        "<b>aceptación íntegra</b> de este contrato, de las partidas, de las cantidades y de la jornada aquí "
        "establecidas. Desde ese momento las partes quedan obligadas en los términos del presente instrumento."
    )


def register_arial(pdf: FPDF) -> str:
    regular = Path(r"C:\Windows\Fonts\arial.ttf")
    bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
    italic = Path(r"C:\Windows\Fonts\ariali.ttf")
    if not regular.is_file() or not bold.is_file():
        return "Helvetica"
    pdf.add_font("Arial", "", str(regular))
    pdf.add_font("Arial", "B", str(bold))
    if italic.is_file():
        pdf.add_font("Arial", "I", str(italic))
    return "Arial"


class ContractDocument(FPDF):
    font_family = "Arial"

    def footer(self) -> None:
        self.set_y(-16)
        self.set_font(self.font_family, "", 8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, f"Página {self.page_no()}", align="C")


def clause(pdf: FPDF, font: str, html: str, size: float = 11) -> None:
    pdf.set_text_color(0, 0, 0)
    pdf.write_html(f'<p align="justify"><font face="{font}" size="{size}">{html}</font></p>')


def charge_quantity(previous: int | None, quantity: int) -> str:
    if previous is None or previous == quantity:
        return str(quantity)
    return f"{previous} a {quantity}"


def charge_row(pdf: FPDF, font: str, name: str, quantity: str) -> None:
    name_width = pdf.epw * 0.75
    quantity_width = pdf.epw - name_width
    pdf.set_font(font, "", 10)
    name_height = pdf.multi_cell(name_width - 2, 5, name, dry_run=True, output="HEIGHT")
    row_height = max(name_height, 6)
    if pdf.get_y() + row_height > pdf.page_break_trigger:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.15)
    pdf.line(pdf.l_margin, y + row_height, pdf.w - pdf.r_margin, y + row_height)
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, y)
    pdf.multi_cell(name_width - 2, 5, name)
    pdf.set_xy(pdf.l_margin + name_width, y)
    pdf.set_font(font, "B", 10)
    pdf.multi_cell(quantity_width, 5, quantity, align="R")
    pdf.set_y(y + row_height)


def contract_pdf(
    *,
    updated: bool,
    client_name: str,
    client_phone: str,
    address: str,
    shift_start: str,
    shift_end: str,
    work_days: str,
    lines: list[tuple[str, int | None, int]],
) -> bytes:
    pdf = ContractDocument()
    font = register_arial(pdf)
    pdf.font_family = font
    pdf.set_compression(False)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 16, 20)
    pdf.add_page()
    mark = logo_path()
    if mark is not None:
        try:
            pdf.image(str(mark), x=20, y=12, w=68)
            pdf.set_y(34)
        except Exception:
            pdf.set_y(16)
    else:
        pdf.set_y(16)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(6)
    title = "ACTUALIZACIÓN DE CONTRATO DE PRESTACIÓN DE SERVICIOS" if updated else "CONTRATO DE PRESTACIÓN DE SERVICIOS"
    pdf.set_font(font, "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 6, title, align="C")
    pdf.ln(1)
    pdf.set_font(font, "", 10)
    pdf.cell(0, 5, f"Santiago, {issue_date()}.", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    client = html_text(client_name or "el cliente")
    phone = html_text(client_phone or "no informado")
    place = html_text(address or "el domicilio que indique el Cliente")
    days = html_text(work_day_label(work_days) or "los que las partes fijen")
    clause(
        pdf,
        font,
        "En Santiago de Chile, entre <b>Vitrificados Chile</b>, en adelante el <b>Prestador</b>, y "
        f"<b>{client}</b>, teléfono {phone}, en adelante el <b>Cliente</b>, "
        "se conviene lo siguiente:",
    )
    clause(
        pdf,
        font,
        "<b>Primero: Objeto.</b> El Prestador ejecutará el servicio de vitrificado de pisos de madera "
        f"en el inmueble ubicado en <b>{place}</b>.",
    )
    clause(
        pdf,
        font,
        "<b>Segundo: Jornada.</b> Los trabajos se realizarán entre las "
        f"<b>{html_text(shift_start)}</b> y las <b>{html_text(shift_end)}</b> horas, los días <b>{days}</b>. "
        "El Cliente permitirá el acceso del personal en ese horario.",
    )
    clause(
        pdf,
        font,
        "<b>Tercero: Alcance.</b> La ejecución comprende exclusivamente las partidas y cantidades "
        "que se indican. Lo que no figure en este cuadro no forma parte del encargo.",
    )
    pdf.set_font(font, "B", 10)
    pdf.set_text_color(0, 0, 0)
    name_width = pdf.epw * 0.75
    pdf.set_x(pdf.l_margin)
    pdf.cell(name_width, 6, "Partida")
    pdf.cell(pdf.epw - name_width, 6, "Cantidad", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.3)
    rule = pdf.get_y()
    pdf.line(pdf.l_margin, rule, pdf.w - pdf.r_margin, rule)
    if not lines:
        charge_row(pdf, font, "Sin partidas con cantidad.", "-")
    for name, previous, quantity in lines:
        charge_row(pdf, font, name, charge_quantity(previous, quantity))
    pdf.ln(3)
    clause(
        pdf,
        font,
        "<b>Cuarto: Modificaciones.</b> Todo cambio de partida o de cantidad solo producirá efecto "
        "si consta <b>por escrito</b>. El instrumento actualizado sustituye al anterior en lo modificado.",
    )
    clause(pdf, font, acceptance_clause(updated=updated), size=8)
    pdf.ln(2)
    pdf.set_font(font, "", 10)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, "En comprobante, las partes firman dos ejemplares de igual tenor y fecha.", align="J")
    pdf.ln(12)
    if pdf.get_y() + 18 > pdf.page_break_trigger:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, y, pdf.l_margin + 62, y)
    pdf.line(pdf.l_margin + 96, y, pdf.l_margin + 158, y)
    pdf.set_xy(pdf.l_margin, y + 2)
    pdf.set_font(font, "B", 9)
    pdf.cell(96, 5, "El Cliente")
    pdf.cell(0, 5, "El Prestador", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin)
    pdf.set_font(font, "", 8)
    pdf.cell(96, 4, client_name or "")
    pdf.cell(0, 4, "Vitrificados Chile", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def palmeta_change_pdf(
    *,
    work_name: str,
    address: str,
    client_name: str,
    previous_count: int,
    next_count: int,
    square_meters: float,
    unit_cost: float,
) -> bytes:
    previous_amount = palmeta_amount(previous_count, unit_cost)
    next_amount = palmeta_amount(next_count, unit_cost)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)
    mark = logo_path()
    if mark is not None:
        try:
            pdf.image(str(mark), x=15, y=12, w=28)
            pdf.set_xy(pdf.l_margin, 44)
        except Exception:
            pdf.set_xy(pdf.l_margin, 15)
    else:
        pdf.set_xy(pdf.l_margin, 15)
    pdf.set_text_color(93, 62, 56)
    write_line(pdf, "Vitrificados Chile", height=10, bold=True, size=16)
    pdf.set_text_color(40, 40, 40)
    write_line(pdf, "Propuesta de cambio en la cantidad de palmetas", size=12)
    pdf.ln(2)
    lines = [
        f"Obra: {work_name}",
        f"Direccion: {address}",
        f"Cliente: {client_name}",
        f"Retape: {square_meters:g} m2",
        f"Palmetas actuales: {previous_count}",
        f"Palmetas propuestas: {next_count}",
        f"Costo actual de palmetas: {money(previous_amount)}",
        f"Costo con el cambio: {money(next_amount)}",
    ]
    for line in lines:
        write_line(pdf, line)
    pdf.ln(4)
    write_line(pdf, "Responde por este WhatsApp si aceptas o no el cambio.", bold=True, size=12)
    return bytes(pdf.output())
