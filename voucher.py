"""
Generador de comprobantes/vouchers en imagen PNG usando Pillow.
Comprobantes numerados consecutivamente.
"""

import os
import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

VOUCHERS_DIR = os.getenv("VOUCHERS_DIR", "vouchers")
os.makedirs(VOUCHERS_DIR, exist_ok=True)

COUNTER_FILE = os.path.join(VOUCHERS_DIR, "counter.json")

# Paleta de colores
BG_COLOR      = (18, 36, 58)
ACCENT_COLOR  = (255, 193, 7)
TEXT_COLOR     = (255, 255, 255)
SUBTLE_COLOR  = (160, 180, 200)
BORDER_COLOR  = (255, 193, 7)
CARD_COLOR    = (28, 52, 80)
GREEN_COLOR   = (46, 160, 67)


def _next_voucher_number() -> int:
    """Retorna el siguiente número consecutivo de comprobante."""
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {"last": 0}
    data["last"] += 1
    with open(COUNTER_FILE, "w") as f:
        json.dump(data, f)
    return data["last"]


def _get_font(size: int, bold: bool = False):
    font_names = (
        ["arialbd.ttf", "Arial Bold.ttf"] if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except (IOError, OSError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _draw_rounded_rect(draw, xy, radius, fill, outline=None, outline_width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=outline_width)


def generate_voucher(
    user_name: str,
    reward_name: str,
    provider: str,
    points_used: int,
    new_balance: int,
    voucher_code: str
) -> str:
    """Genera una imagen de voucher numerado y retorna la ruta del archivo."""

    voucher_num = _next_voucher_number()
    num_str = f"RC-{voucher_num:05d}"

    W, H = 700, 500
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Decoración de fondo
    draw.ellipse((-60, -60, 160, 160), fill=(30, 55, 90))
    draw.ellipse((560, 340, 780, 560), fill=(30, 55, 90))

    # Borde dorado
    _draw_rounded_rect(draw, (12, 12, W - 12, H - 12),
                       radius=16, fill=None, outline=BORDER_COLOR, outline_width=3)

    # Fuentes
    title_font = _get_font(20, bold=True)
    sub_font   = _get_font(12)
    body_font  = _get_font(15)
    bold_font  = _get_font(17, bold=True)
    code_font  = _get_font(30, bold=True)
    num_font   = _get_font(14, bold=True)

    # ── Encabezado ──
    draw.rounded_rectangle((12, 12, W - 12, 80), radius=16, fill=ACCENT_COLOR)
    draw.rectangle((12, 50, W - 12, 80), fill=ACCENT_COLOR)
    draw.text((W // 2, 35), "COMPROBANTE DE CANJE", font=title_font,
              fill=(18, 36, 58), anchor="mm")
    draw.text((W // 2, 58), "Red Colaboracion  -  Turismo Colaborativo",
              font=sub_font, fill=(60, 40, 10), anchor="mm")

    # ── Número de comprobante (esquina superior derecha) ──
    _draw_rounded_rect(draw, (W - 170, 90, W - 30, 118),
                       radius=8, fill=GREEN_COLOR)
    draw.text((W - 100, 104), f"No. {num_str}", font=num_font,
              fill=TEXT_COLOR, anchor="mm")

    y = 95

    # ── Premio ──
    _draw_rounded_rect(draw, (30, y, W - 185, y + 55), radius=10, fill=CARD_COLOR)
    draw.text((50, y + 8), "PREMIO", font=sub_font, fill=ACCENT_COLOR)
    draw.text((50, y + 25), reward_name[:35], font=bold_font, fill=TEXT_COLOR)

    y += 68

    # ── Proveedor / Usuario ──
    col1_x, col2_x = 50, W // 2 + 10
    _draw_rounded_rect(draw, (30, y, W // 2 - 15, y + 65), radius=10, fill=CARD_COLOR)
    _draw_rounded_rect(draw, (W // 2 + 5, y, W - 30, y + 65), radius=10, fill=CARD_COLOR)

    draw.text((col1_x, y + 8), "PROVEEDOR", font=sub_font, fill=ACCENT_COLOR)
    draw.text((col1_x, y + 26), provider[:22], font=body_font, fill=TEXT_COLOR)

    draw.text((col2_x, y + 8), "USUARIO", font=sub_font, fill=ACCENT_COLOR)
    draw.text((col2_x, y + 26), user_name[:22], font=body_font, fill=TEXT_COLOR)

    y += 78

    # ── Puntos usados / Saldo restante ──
    _draw_rounded_rect(draw, (30, y, W // 2 - 15, y + 65), radius=10, fill=CARD_COLOR)
    _draw_rounded_rect(draw, (W // 2 + 5, y, W - 30, y + 65), radius=10, fill=CARD_COLOR)

    draw.text((col1_x, y + 8), "PUNTOS CANJEADOS", font=sub_font, fill=ACCENT_COLOR)
    draw.text((col1_x, y + 26), f"{points_used} pts", font=bold_font, fill=TEXT_COLOR)

    draw.text((col2_x, y + 8), "SALDO RESTANTE", font=sub_font, fill=ACCENT_COLOR)
    draw.text((col2_x, y + 26), f"{new_balance} pts", font=bold_font, fill=TEXT_COLOR)

    y += 78

    # ── Código de canje ──
    _draw_rounded_rect(draw, (30, y, W - 30, y + 62),
                       radius=12, fill=(10, 22, 40), outline=ACCENT_COLOR, outline_width=2)
    draw.text((W // 2, y + 12), "CODIGO DE CANJE", font=sub_font, fill=ACCENT_COLOR, anchor="mm")
    draw.text((W // 2, y + 40), voucher_code, font=code_font, fill=ACCENT_COLOR, anchor="mm")

    y += 72

    # ── Fecha y número ──
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    draw.text((50, y + 5), f"Fecha: {date_str}", font=sub_font, fill=SUBTLE_COLOR)
    draw.text((W - 50, y + 5), f"Comprobante {num_str}", font=sub_font,
              fill=SUBTLE_COLOR, anchor="rm")

    # ── Pie ──
    draw.text((W // 2, H - 16),
              "Presenta este comprobante al momento de redimir tu premio",
              font=sub_font, fill=SUBTLE_COLOR, anchor="mm")

    # Guardar
    out_path = os.path.join(VOUCHERS_DIR, f"voucher_{num_str}_{voucher_code}.png")
    img.save(out_path, "PNG")
    return out_path
