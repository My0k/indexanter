from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import os
import csv
import re
import unicodedata
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Cambiar en producción

# Configuración
INPUT_DIR = 'input'
DOCUMENTS_DIR = 'documentos'

# Crear directorios si no existen
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(DOCUMENTS_DIR, exist_ok=True)

# ---------- Utilidades de procesamiento ----------

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

def process_pdf_to_images(pdf_path: Path) -> dict:
    """Procesa PDF y genera imágenes y CSV básico"""
    stem = pdf_path.stem
    doc_dir = Path(DOCUMENTS_DIR) / stem
    img_dir = doc_dir / "imagenes"
    
    ensure_dir(doc_dir)
    ensure_dir(img_dir)
    
    csv_path = doc_dir / f"{stem}.csv"
    
    # Crear CSV con headers básicos
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["numero", "nombre_jpg", "has_comprobante", "folio", "q1_ocr", "q2_ocr"])
    
    try:
        doc = fitz.open(pdf_path)
        n_pages = doc.page_count
        
        processed_pages = []
        
        for i in range(n_pages):
            page_num = i + 1
            page_4d = f"{page_num:04d}"
            jpg_name = f"{page_4d}.jpg"
            jpg_path = img_dir / jpg_name
            
            # Renderizar página a JPG
            page = doc.load_page(i)
            mat = fitz.Matrix(2.0, 2.0)  # ~300 DPI
            pix = page.get_pixmap(matrix=mat, alpha=False)
            save_jpg(pix, jpg_path)
            
            # OCR básico para detectar comprobantes
            try:
                ocr_page_text = pytesseract.image_to_string(Image.open(jpg_path), lang="spa+eng")
                has_comp = contains_comprobante(ocr_page_text)
                folio = extract_first_folio_token(ocr_page_text) if has_comp else None
            except Exception as e:
                print(f"Error OCR en página {page_4d}: {e}")
                has_comp = False
                folio = None
            
            # Escribir datos básicos al CSV
            with open(csv_path, "a", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([page_4d, jpg_name, "SI" if has_comp else "NO", folio or "", "", ""])
            
            processed_pages.append({
                'numero': page_4d,
                'nombre_jpg': jpg_name,
                'has_comprobante': has_comp,
                'folio': folio
            })
        
        doc.close()
        
        return {
            'success': True,
            'pages_processed': n_pages,
            'document_dir': doc_dir,
            'csv_path': csv_path,
            'pages': processed_pages
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def extract_data_from_document(doc_name: str) -> dict:
    """Extrae datos detallados de un documento ya procesado"""
    doc_dir = Path(DOCUMENTS_DIR) / doc_name
    img_dir = doc_dir / "imagenes"
    csv_path = doc_dir / f"{doc_name}.csv"
    
    if not csv_path.exists():
        return {'success': False, 'error': 'CSV no encontrado'}
    
    # Leer CSV existente
    rows = []
    with open(csv_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)
    
    extracted_count = 0
    
    # Procesar cada fila que tenga comprobante
    for row in rows:
        if row['has_comprobante'] == 'SI' and row['folio']:
            jpg_path = img_dir / row['nombre_jpg']
            if jpg_path.exists():
                try:
                    # Extraer OCR de cuadrantes específicos
                    q1_text = ocr_text_from_region(jpg_path, (0, 0, 515, 190))
                    q2_text = ocr_text_from_region(jpg_path, (1154, 0, 10**9, 174))
                    
                    # Actualizar datos en la fila
                    row['q1_ocr'] = q1_text
                    row['q2_ocr'] = q2_text
                    extracted_count += 1
                    
                except Exception as e:
                    print(f"Error extrayendo datos de {row['nombre_jpg']}: {e}")
    
    # Reescribir CSV con datos actualizados
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["numero", "nombre_jpg", "has_comprobante", "folio", "q1_ocr", "q2_ocr"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    return {
        'success': True,
        'extracted_count': extracted_count,
        'total_rows': len(rows)
    }

def read_document_data(doc_name: str) -> list:
    """Lee los datos del CSV de un documento"""
    csv_path = Path(DOCUMENTS_DIR) / doc_name / f"{doc_name}.csv"
    if not csv_path.exists():
        return []
    
    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)
    except Exception as e:
        print(f"Error leyendo CSV: {e}")
    
    return rows

def update_document_data(doc_name: str, page_number: str, updated_data: dict) -> bool:
    """Actualiza los datos de una página específica"""
    csv_path = Path(DOCUMENTS_DIR) / doc_name / f"{doc_name}.csv"
    if not csv_path.exists():
        return False
    
    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)
        
        # Encontrar y actualizar la fila correspondiente
        for row in rows:
            if row['numero'] == page_number:
                row.update(updated_data)
                break
        
        # Reescribir CSV
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["numero", "nombre_jpg", "has_comprobante", "folio", "q1_ocr", "q2_ocr"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        return True
        
    except Exception as e:
        print(f"Error actualizando datos: {e}")
        return False

# ---------- Decoradores y rutas ----------

def require_login(f):
    """Decorador para requerir login"""
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@app.route('/')
def index():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('documents'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == 'chepss' and password == 'chepss123':
            session['logged_in'] = True
            return redirect(url_for('documents'))
        else:
            flash('Credenciales incorrectas')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/documents')
@require_login
def documents():
    # Obtener PDFs del directorio input
    pdf_files = []
    if os.path.exists(INPUT_DIR):
        pdf_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.pdf')]
    
    return render_template('documents.html', pdf_files=pdf_files)

@app.route('/process_pdf', methods=['POST'])
@require_login
def process_pdf():
    pdf_file = request.form.get('pdf_file')
    if pdf_file:
        pdf_path = Path(INPUT_DIR) / pdf_file
        if pdf_path.exists():
            result = process_pdf_to_images(pdf_path)
            if result['success']:
                flash(f'PDF procesado exitosamente: {result["pages_processed"]} páginas generadas')
            else:
                flash(f'Error procesando PDF: {result["error"]}')
        else:
            flash('Archivo PDF no encontrado')
    return redirect(url_for('documents'))

@app.route('/extract')
@require_login
def extract():
    # Obtener documentos procesados
    processed_docs = []
    if os.path.exists(DOCUMENTS_DIR):
        for item in os.listdir(DOCUMENTS_DIR):
            doc_path = Path(DOCUMENTS_DIR) / item
            if doc_path.is_dir():
                csv_path = doc_path / f"{item}.csv"
                if csv_path.exists():
                    # Contar comprobantes disponibles para extracción
                    data = read_document_data(item)
                    comprobantes_count = sum(1 for row in data if row.get('has_comprobante') == 'SI')
                    processed_docs.append({
                        'name': item,
                        'comprobantes_count': comprobantes_count,
                        'total_pages': len(data)
                    })
    
    return render_template('extract.html', processed_docs=processed_docs)

@app.route('/extract_data', methods=['POST'])
@require_login
def extract_data():
    doc_name = request.form.get('doc_name')
    if doc_name:
        result = extract_data_from_document(doc_name)
        if result['success']:
            flash(f'Datos extraídos: {result["extracted_count"]} comprobantes procesados de {result["total_rows"]} páginas')
        else:
            flash(f'Error extrayendo datos: {result["error"]}')
    return redirect(url_for('extract'))

@app.route('/index_view')
@require_login
def index_view():
    # Obtener documentos con imágenes
    docs_with_images = []
    if os.path.exists(DOCUMENTS_DIR):
        for doc_dir in os.listdir(DOCUMENTS_DIR):
            doc_path = Path(DOCUMENTS_DIR) / doc_dir
            if doc_path.is_dir():
                images_path = doc_path / 'imagenes'
                csv_path = doc_path / f"{doc_dir}.csv"
                if images_path.exists() and csv_path.exists():
                    data = read_document_data(doc_dir)
                    if data:
                        docs_with_images.append({
                            'name': doc_dir,
                            'total_images': len(data),
                            'comprobantes_count': sum(1 for row in data if row.get('has_comprobante') == 'SI')
                        })
    
    return render_template('index.html', docs_with_images=docs_with_images)

@app.route('/view_document/<doc_name>')
@require_login
def view_document(doc_name):
    page = request.args.get('page', 1, type=int)
    
    # Obtener datos del documento
    data = read_document_data(doc_name)
    if not data:
        flash('No se encontraron datos para este documento')
        return redirect(url_for('index_view'))
    
    # Validar página
    if page < 1 or page > len(data):
        page = 1
    
    current_data = data[page - 1]
    
    return render_template('view_document.html', 
                         doc_name=doc_name,
                         current_data=current_data,
                         current_page=page,
                         total_pages=len(data),
                         has_prev=page > 1,
                         has_next=page < len(data))

@app.route('/update_page_data', methods=['POST'])
@require_login
def update_page_data():
    doc_name = request.form.get('doc_name')
    page_number = request.form.get('page_number')
    
    updated_data = {
        'folio': request.form.get('folio', ''),
        'q1_ocr': request.form.get('q1_ocr', ''),
        'q2_ocr': request.form.get('q2_ocr', ''),
        'has_comprobante': 'SI' if request.form.get('has_comprobante') else 'NO'
    }
    
    if update_document_data(doc_name, page_number, updated_data):
        flash('Datos actualizados correctamente')
    else:
        flash('Error actualizando datos')
    
    current_page = request.form.get('current_page', 1, type=int)
    return redirect(url_for('view_document', doc_name=doc_name, page=current_page))

@app.route('/static/documentos/<path:filename>')
@require_login
def serve_document_file(filename):
    """Servir archivos estáticos de documentos"""
    return send_from_directory(DOCUMENTS_DIR, filename)

if __name__ == '__main__':
    app.run(debug=True)
