import csv
import re
import unicodedata
from pathlib import Path
from PIL import Image
import pytesseract
import os

def normalize_text(s: str) -> str:
    """Normaliza texto para búsqueda insensible a acentos y mayúsculas"""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s

def contains_comprobante(text: str) -> bool:
    """Detecta si el texto contiene la palabra 'comprobante'"""
    return "comprobante" in normalize_text(text)

def extract_first_folio_token(text: str) -> str | None:
    """Busca 8 dígitos sin guiones ni más dígitos a la derecha"""
    pattern = re.compile(r'(?<!\d)(\d{8})(?![\d-])')
    m = pattern.search(text)
    return m.group(1) if m else None

def clamp(val, lo, hi):
    """Limita un valor entre un mínimo y máximo"""
    return max(lo, min(val, hi))

def ocr_text_from_region(jpg_path: Path, box: tuple[int, int, int, int]) -> str:
    """Extrae texto OCR de una región específica de la imagen"""
    try:
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
    except Exception as e:
        print(f"Error en OCR de región: {e}")
        return ""

def process_document_ocr(doc_name: str) -> bool:
    """
    Procesa un documento para extraer datos con OCR
    Lee el CSV existente y añade/actualiza columnas: folio, q1, q2
    Actualiza el CSV después de procesar cada imagen
    """
    try:
        doc_folder = Path('documentos') / doc_name
        csv_path = doc_folder / f"{doc_name}.csv"
        images_folder = doc_folder / 'imagenes'
        
        if not csv_path.exists():
            print(f"Error: No se encontró el CSV {csv_path}")
            return False
        
        if not images_folder.exists():
            print(f"Error: No se encontró la carpeta de imágenes {images_folder}")
            return False
        
        # Leer CSV existente
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames)
            rows = list(reader)
        
        # Verificar si ya tiene las columnas de OCR y añadirlas si no existen
        new_columns = []
        if 'folio' not in fieldnames:
            new_columns.append('folio')
        if 'q1' not in fieldnames:
            new_columns.append('q1')
        if 'q2' not in fieldnames:
            new_columns.append('q2')
        
        # Actualizar fieldnames
        updated_fieldnames = fieldnames + new_columns
        
        # Procesar cada fila/imagen
        for i, row in enumerate(rows):
            img_name = row.get('nombre_img', '')
            img_path = images_folder / img_name
            
            if img_path.exists():
                print(f"Procesando {img_name} ({i+1}/{len(rows)})...")
                
                # OCR página completa
                try:
                    ocr_page_text = pytesseract.image_to_string(Image.open(img_path), lang="spa+eng")
                except Exception as e:
                    print(f"Error de OCR en {img_name}: {e}")
                    ocr_page_text = ""
                
                # Extraer folio si contiene comprobante
                has_comp = contains_comprobante(ocr_page_text)
                folio = extract_first_folio_token(ocr_page_text) if has_comp else ""
                
                # Solo extraer q1 y q2 si se encontró folio
                q1_text = ""
                q2_text = ""
                if folio:
                    q1_text = ocr_text_from_region(img_path, (0, 0, 515, 190))
                    q2_text = ocr_text_from_region(img_path, (1154, 0, 10**9, 174))
                
                # Actualizar/sobrescribir valores en el row
                row['folio'] = folio
                row['q1'] = q1_text
                row['q2'] = q2_text
                
                if folio:
                    print(f"  ✅ Folio encontrado: {folio}")
                    print(f"  Q1: {q1_text[:50]}{'...' if len(q1_text)>50 else ''}")
                    print(f"  Q2: {q2_text[:50]}{'...' if len(q2_text)>50 else ''}")
                else:
                    print(f"  ❌ Sin folio - Valores vacíos para cuadrantes")
                
                # Escribir CSV actualizado después de cada imagen
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=updated_fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                
                print(f"  💾 CSV actualizado")
                
            else:
                print(f"Advertencia: Imagen {img_name} no encontrada")
                # Añadir valores vacíos
                row['folio'] = ""
                row['q1'] = ""
                row['q2'] = ""
                
                # Escribir CSV también para imágenes no encontradas
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=updated_fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
        
        print(f"✅ Extracción completada para {doc_name}")
        print(f"📄 CSV final: {csv_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error procesando {doc_name}: {str(e)}")
        return False
