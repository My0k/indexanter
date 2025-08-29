#!/usr/bin/env python3
"""
Procesa un PDF página por página:
1. Renderiza a JPG para OCR.
2. Detecta si contiene la palabra "Comprobante".
3. Si contiene "Comprobante":
   - Extrae el primer folio (8 dígitos, sin guiones ni dígitos a la derecha).
   - OCR de cuadrante_1 y cuadrante_2.
   - Guarda un PDF de esa página en comprobantes_<nombrepdf>/:
       * <folio>.pdf si encontró folio
       * noencontrado_0001.pdf, noencontrado_0002.pdf ... si no.
4. Registra todo en un CSV: jpg_name, page_4d, has_comprobante, folio, q1_ocr, q2_ocr, saved_pdf_name.

Controles:
  ENTER = siguiente página
  "all" = procesa todas sin pausar
  "q" = salir
"""

import sys
import csv
import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

# ---------- Utilidades ----------

def normalize_text(s: str) -> str:
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s

def contains_comprobante(text: str) -> bool:
    return "comprobante" in normalize_text(text)

def extract_first_folio_token(text: str) -> str | None:
    """Busca 8 dígitos sin guiones ni más dígitos a la derecha."""
    pattern = re.compile(r'(?<!\d)(\d{8})(?![\d-])')
    m = pattern.search(text)
    return m.group(1) if m else None

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def save_jpg(pix: fitz.Pixmap, out_path: Path, quality: int = 90):
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img.save(out_path, format="JPEG", quality=quality, optimize=True)

def clamp(val, lo, hi):
    return max(lo, min(val, hi))

def ocr_text_from_region(jpg_path: Path, box: tuple[int, int, int, int]) -> str:
    img = Image.open(jpg_path).convert("RGB")
    W, H = img.size
    l, t, r, b = box
    l, t = clamp(l, 0, W), clamp(t, 0, H)
    r, b = clamp(r, 0, W), clamp(b, 0, H)
    if r <= l or b <= t:
        return ""
    crop = img.crop((l, t, r, b))
    txt = pytesseract.image_to_string(crop, lang="spa+eng")
    return re.sub(r"\s+", " ", txt).strip()

def save_single_page_pdf(src_doc: fitz.Document, page_index: int, out_path: Path) -> Path:
    new_doc = fitz.open()
    new_doc.insert_pdf(src_doc, from_page=page_index, to_page=page_index)
    new_doc.save(out_path)
    new_doc.close()
    return out_path

# ---------- Principal ----------

def main():
    pdf_input = input("Ruta del PDF: ").strip().strip('"').strip("'")
    if not pdf_input:
        print("No se proporcionó archivo PDF.")
        sys.exit(1)

    pdf_path = Path(pdf_input).expanduser().resolve()
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        print("Archivo no existe o no es un .pdf")
        sys.exit(1)

    stem = pdf_path.stem
    base_dir = pdf_path.parent

    out_img_dir = base_dir / f"{stem}_imgs"
    comprobantes_dir = base_dir / f"comprobantes_{stem}"
    ensure_dir(out_img_dir)
    ensure_dir(comprobantes_dir)

    csv_path = base_dir / f"{stem}.csv"
    write_header = not csv_path.exists()
    csv_file = open(csv_path, "a", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    if write_header:
        csv_writer.writerow([
            "jpg_name", "page_4d", "has_comprobante",
            "folio", "q1_ocr", "q2_ocr", "saved_pdf_name"
        ])

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"No se pudo abrir el PDF: {e}")
        csv_file.close()
        sys.exit(1)

    n_pages = doc.page_count
    print(f"PDF cargado: {pdf_path.name} | Páginas: {n_pages}")
    print('Controles: ENTER = siguiente | "all" = procesar todas | "q" = salir')

    mode_all = False

    try:
        for i in range(n_pages):
            page_num = i + 1
            page_4d = f"{page_num:04d}"

            # ---- Render a JPG para OCR
            jpg_name = f"{page_4d}.jpg"
            jpg_path = out_img_dir / jpg_name
            page = doc.load_page(i)
            mat = fitz.Matrix(2.0, 2.0)  # ~300 DPI
            pix = page.get_pixmap(matrix=mat, alpha=False)
            save_jpg(pix, jpg_path)

            # ---- OCR página completa
            try:
                ocr_page_text = pytesseract.image_to_string(Image.open(jpg_path), lang="spa+eng")
            except Exception as e:
                print(f"[{page_4d}] Error de OCR: {e}")
                ocr_page_text = ""

            has_comp = contains_comprobante(ocr_page_text)
            folio = extract_first_folio_token(ocr_page_text) if has_comp else None

            q1_text = ""
            q2_text = ""
            saved_pdf_name = ""

            if has_comp:
                # OCR en cuadrantes
                q1_text = ocr_text_from_region(jpg_path, (0, 0, 515, 190))
                q2_text = ocr_text_from_region(jpg_path, (1154, 0, 10**9, 174))

                # Guardado en "comprobantes_<stem>/"
                if folio:
                    comp_name = f"{folio}.pdf"
                else:
                    comp_name = f"noencontrado_{page_4d}.pdf"

                comp_path = comprobantes_dir / comp_name
                save_single_page_pdf(doc, i, comp_path)
                saved_pdf_name = comp_name

                print(f"[{page_4d}] Comprobante: SI | Folio: {folio if folio else '(no encontrado)'} | Guardado en {comp_name}")
                print(f"   q1_ocr: {q1_text[:160]}{'...' if len(q1_text)>160 else ''}")
                print(f"   q2_ocr: {q2_text[:160]}{'...' if len(q2_text)>160 else ''}")
            else:
                print(f"[{page_4d}] Comprobante: NO")

            # ---- CSV append
            csv_writer.writerow([
                jpg_name, page_4d, "SI" if has_comp else "NO",
                folio or "", q1_text, q2_text, saved_pdf_name
            ])

            # ---- Control
            if not mode_all and i < n_pages - 1:
                user_cmd = input().strip().lower()
                if user_cmd == "all":
                    mode_all = True
                elif user_cmd == "q":
                    print("Salida solicitada por el usuario.")
                    break

        print(f"\nListo.")
        print(f"Imágenes: {out_img_dir}")
        print(f"Comprobantes: {comprobantes_dir}")
        print(f"CSV: {csv_path}")

    finally:
        csv_file.close()
        doc.close()

if __name__ == "__main__":
    main()
