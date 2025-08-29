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

def extract_rut_from_text(text: str) -> str:
    """
    Extrae el primer RUT del texto con varios formatos posibles:
    X.XXX.XXX-X, XX.XXX.XXX-X, XXXXXXX-X, XXXXXXXX, XXXXXXXXX, XXXXXXXX-X
    """
    if not text:
        return ""
    
    # Patrones para diferentes formatos de RUT
    patterns = [
        # Con puntos y guión: X.XXX.XXX-X o XX.XXX.XXX-X
        r'\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b',
        # Sin puntos con guión: XXXXXXX-X o XXXXXXXX-X
        r'\b\d{7,8}-[\dkK]\b',
        # Solo números de 7, 8 o 9 dígitos
        r'\b\d{7,9}\b'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).upper()
    
    return ""

def extract_nombre_from_q1(text: str, rut: str) -> str:
    """
    Extrae el nombre desde el inicio del texto hasta antes del RUT
    """
    if not text or not rut:
        return ""
    
    # Buscar la posición del RUT en el texto
    rut_pos = text.upper().find(rut.upper())
    if rut_pos == -1:
        # Si no encuentra el RUT exacto, buscar por patrones similares
        # Quitar puntos y guiones para búsqueda flexible
        clean_rut = re.sub(r'[.-]', '', rut)
        for i in range(len(text) - len(clean_rut) + 1):
            text_segment = re.sub(r'[.-]', '', text[i:i+len(clean_rut)])
            if text_segment == clean_rut:
                rut_pos = i
                break
    
    if rut_pos > 0:
        nombre = text[:rut_pos].strip()
        # Limpiar el nombre de caracteres extraños al final
        nombre = re.sub(r'\s+', ' ', nombre).strip()
        return nombre
    
    return ""

def extract_fecha_from_text(text: str) -> str:
    """
    Extrae fecha del texto con formatos como DD/MM/YYYY, DD-MM-YYYY, etc.
    """
    if not text:
        return ""
    
    # Patrones para diferentes formatos de fecha
    patterns = [
        # DD/MM/YYYY
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',
        # DD-MM-YYYY
        r'\b\d{1,2}-\d{1,2}-\d{4}\b',
        # DD.MM.YYYY
        r'\b\d{1,2}\.\d{1,2}\.\d{4}\b',
        # DD MM YYYY (con espacios)
        r'\b\d{1,2}\s+\d{1,2}\s+\d{4}\b'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    
    return ""

def process_document_ocr(doc_name: str) -> bool:
    """
    Procesa un documento para extraer datos con OCR
    Lee el CSV existente y añade/actualiza columnas: folio, q1, q2, rut, fecha, nombre
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
        for col in ['folio', 'q1', 'q2', 'rut', 'fecha', 'nombre']:
            if col not in fieldnames:
                new_columns.append(col)
        
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
                rut = ""
                fecha = ""
                nombre = ""
                
                if folio:
                    q1_text = ocr_text_from_region(img_path, (0, 0, 515, 190))
                    q2_text = ocr_text_from_region(img_path, (1154, 0, 10**9, 174))
                    
                    # Extraer RUT, fecha y nombre
                    rut = extract_rut_from_text(q1_text)
                    fecha = extract_fecha_from_text(q2_text)
                    nombre = extract_nombre_from_q1(q1_text, rut)
                
                # Actualizar/sobrescribir valores en el row
                row['folio'] = folio
                row['q1'] = q1_text
                row['q2'] = q2_text
                row['rut'] = rut
                row['fecha'] = fecha
                row['nombre'] = nombre
                
                if folio:
                    print(f"  ✅ Folio: {folio}")
                    print(f"  🆔 RUT: {rut}")
                    print(f"  📅 Fecha: {fecha}")
                    print(f"  👤 Nombre: {nombre[:50]}{'...' if len(nombre)>50 else ''}")
                    print(f"  Q1: {q1_text[:30]}{'...' if len(q1_text)>30 else ''}")
                    print(f"  Q2: {q2_text[:30]}{'...' if len(q2_text)>30 else ''}")
                else:
                    print(f"  ❌ Sin folio - Valores vacíos")
                
                # Escribir CSV actualizado después de cada imagen
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=updated_fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                
                print(f"  💾 CSV actualizado")
                
            else:
                print(f"Advertencia: Imagen {img_name} no encontrada")
                # Añadir valores vacíos
                for col in ['folio', 'q1', 'q2', 'rut', 'fecha', 'nombre']:
                    row[col] = ""
                
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
