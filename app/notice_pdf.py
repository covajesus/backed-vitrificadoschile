from datetime import date
from pathlib import Path

from fpdf import FPDF

from app.domain import format_quantity, palmeta_amount

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


def fit_line(pdf: FPDF, text: str, width: float) -> str:
    value = pdf_text(text)
    if pdf.get_string_width(value) <= width:
        return value
    trimmed = value
    while trimmed and pdf.get_string_width(f"{trimmed}...") > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}..."


def money_row(pdf: FPDF, x: float, y: float, width: float, label: str, value: str, *, color: tuple[int, int, int] = (30, 30, 30)) -> float:
    label_width = width * 0.62
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*color)
    pdf.set_xy(x, y)
    pdf.cell(label_width, 6, fit_line(pdf, f"  {label}", label_width - 2))
    pdf.set_xy(x + label_width, y)
    pdf.cell(width - label_width, 6, pdf_text(value), align="R")
    pdf.set_draw_color(226, 226, 226)
    pdf.set_line_width(0.15)
    pdf.line(x, y + 6, x + width, y + 6)
    return y + 6


def section_head(pdf: FPDF, x: float, y: float, width: float, title: str, value: str) -> float:
    label_width = width * 0.62
    pdf.set_fill_color(243, 244, 246)
    pdf.set_text_color(17, 24, 39)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(x, y)
    pdf.cell(label_width, 7, pdf_text(f"  {title}"), fill=True)
    pdf.set_xy(x + label_width, y)
    pdf.cell(width - label_width, 7, pdf_text(value), align="R", fill=True)
    return y + 7


def settlement_pdf(
    *,
    person: str,
    period: str,
    items: list[tuple[str, int]],
    total: int,
    document_id: str = "",
    role: str = "",
) -> bytes:
    pdf = FPDF()
    pdf.set_compression(False)
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(14, 14, 14)
    pdf.add_page()
    content = pdf.epw
    gap = 8
    column = (content - gap) / 2
    left = pdf.l_margin
    right = left + column + gap
    mark = logo_path()
    if mark is not None:
        try:
            pdf.image(str(mark), x=pdf.w - pdf.r_margin - 42, y=12, w=42)
        except Exception:
            pass
    pdf.set_xy(left, 16)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(content - 48, 8, pdf_text("Liquidación de Sueldo"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(left)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(content - 48, 5, pdf_text("Empleador: Vitrificados Chile"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(left)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(content - 48, 5, pdf_text(f"Mes: {period_label(period)}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_draw_color(229, 231, 235)
    pdf.set_line_width(0.2)
    pdf.line(left, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    facts = (
        ("Sr(a):", person or "Trabajador"),
        ("RUT:", document_id.strip() or "-"),
        ("Cargo:", role.strip() or "-"),
    )
    for label, value in facts:
        pdf.set_x(left)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(17, 24, 39)
        pdf.cell(18, 5, pdf_text(label))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, pdf_text(value), new_x="LMARGIN", new_y="NEXT")
    haberes = [(label, amount) for label, amount in items if amount >= 0]
    deductions = [(label, amount) for label, amount in items if amount < 0]
    haber_total = sum(amount for _, amount in haberes)
    deduction_total = sum(abs(amount) for _, amount in deductions)
    y = pdf.get_y() + 8
    y_left = section_head(pdf, left, y, column, "Haberes", money(haber_total))
    if haberes:
        for label, amount in haberes:
            y_left = money_row(pdf, left, y_left, column, label, money(amount))
    else:
        y_left = money_row(pdf, left, y_left, column, "Sin haberes en el periodo.", "-")
    y_right = section_head(pdf, right, y, column, "Deducciones", money(deduction_total))
    if deductions:
        for label, amount in deductions:
            y_right = money_row(pdf, right, y_right, column, label, money(abs(amount)), color=(225, 29, 72))
    else:
        y_right = money_row(pdf, right, y_right, column, "Sin deducciones.", "-", color=(225, 29, 72))
    y = max(y_left, y_right) + 8
    bars = (
        ("TOTAL HABERES", money(haber_total), (243, 244, 246), (17, 24, 39)),
        ("TOTAL DEDUCCIONES", money(deduction_total), (255, 241, 242), (225, 29, 72)),
        ("TOTAL A PAGAR", money(total), (117, 92, 71), (255, 255, 255)),
    )
    for label, value, fill, color in bars:
        pdf.set_fill_color(*fill)
        pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(left, y)
        pdf.cell(content, 8, pdf_text(f"{label}: {value}"), align="C", fill=True)
        y += 8
    pdf.set_xy(left, y + 10)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(55, 65, 81)
    pdf.multi_cell(
        content,
        4.5,
        pdf_text(
            "Certifico que he recibido de Vitrificados Chile a mi entera satisfacción el saldo "
            "indicado en la presente liquidación y no tengo cargo ni cobro posterior que hacer."
        ),
    )
    sign = pdf.get_y() + 16
    pdf.set_draw_color(107, 114, 128)
    pdf.set_line_width(0.3)
    pdf.line(left + 48, sign, left + content - 48, sign)
    pdf.set_xy(left, sign + 2)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(75, 85, 99)
    pdf.cell(content, 5, "FIRMA CONFORME", align="C")
    return bytes(pdf.output())


def issue_date() -> str:
    today = date.today()
    return f"{today.day} de {MONTHS[today.month - 1]} de {today.year}"


def html_text(value: str) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def change_sentence(name: str, previous: float | None, quantity: float) -> str:
    if previous is None or previous == quantity:
        return ""
    if previous == 0:
        return f"Se agrega {name}, cantidad {format_quantity(quantity)}."
    if quantity == 0:
        return f"Se quita {name}."
    return f"{name} pasa de {format_quantity(previous)} a {format_quantity(quantity)}."


def update_note_pdf(lines: list[tuple[str, float | None, float]]) -> bytes:
    sentences = [change_sentence(name, previous, quantity) for name, previous, quantity in lines]
    text = " ".join(sentence for sentence in sentences if sentence) or "No hay cambios en las partidas."
    pdf = FPDF()
    pdf.set_compression(False)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 7, text)
    return bytes(pdf.output())


def acceptance_clause() -> str:
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


def charge_quantity(previous: float | None, quantity: float) -> str:
    shown = format_quantity(quantity)
    if previous is None or previous == quantity:
        return shown
    return f"{format_quantity(previous)} a {shown}"


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
    if updated:
        return update_note_pdf(lines)
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
    title = "CONTRATO DE PRESTACIÓN DE SERVICIOS"
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
    clause(pdf, font, acceptance_clause(), size=8)
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
