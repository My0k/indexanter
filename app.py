from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
import os
import csv
from pdf2image import convert_from_path
import logging
from functions.generate_documentos import process_pdf_to_images_and_csv, get_pdf_name_without_extension
from functions.extraer_datos import process_document_ocr

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Necesario para flash messages

# Configuración básica
app.config['UPLOAD_FOLDER'] = 'input'
app.config['DOCUMENTS_FOLDER'] = 'documentos'

# Crear directorios si no existen
os.makedirs('input', exist_ok=True)
os.makedirs('documentos', exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('static', exist_ok=True)

@app.route('/')
def index():
    """Página principal - Indexación"""
    # Obtener documentos que tienen carpeta en /documentos
    processed_docs = []
    if os.path.exists('documentos'):
        processed_docs = [d for d in os.listdir('documentos') 
                         if os.path.isdir(os.path.join('documentos', d))]
    return render_template('index.html', processed_docs=processed_docs)

@app.route('/view_document/<doc_name>')
def view_document(doc_name):
    """Ver documento específico - primera página"""
    return redirect(url_for('view_document_page', doc_name=doc_name, page=1))

@app.route('/view_document/<doc_name>/<int:page>')
def view_document_page(doc_name, page):
    """Ver página específica de un documento"""
    try:
        doc_folder = os.path.join('documentos', doc_name)
        csv_path = os.path.join(doc_folder, f"{doc_name}.csv")
        
        if not os.path.exists(csv_path):
            flash(f'Error: No se encontró el CSV para {doc_name}', 'error')
            return redirect(url_for('index'))
        
        # Leer datos del CSV
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            flash(f'Error: El CSV de {doc_name} está vacío', 'error')
            return redirect(url_for('index'))
        
        # Validar página
        if page < 1 or page > len(rows):
            page = 1
        
        current_row = rows[page - 1]
        total_pages = len(rows)
        
        # Verificar que la imagen existe
        img_path = os.path.join(doc_folder, current_row.get('path_img', ''))
        img_exists = os.path.exists(img_path)
        
        return render_template('index.html', 
                             processed_docs=[],  # No mostrar selector cuando ya hay uno seleccionado
                             current_doc=doc_name,
                             current_page=page,
                             total_pages=total_pages,
                             current_data=current_row,
                             img_exists=img_exists)
                             
    except Exception as e:
        flash(f'Error al cargar documento: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/save_data/<doc_name>/<int:page>', methods=['POST'])
def save_data(doc_name, page):
    """Guardar cambios en los datos del documento"""
    try:
        doc_folder = os.path.join('documentos', doc_name)
        csv_path = os.path.join(doc_folder, f"{doc_name}.csv")
        
        if not os.path.exists(csv_path):
            flash(f'Error: No se encontró el CSV para {doc_name}', 'error')
            return redirect(url_for('index'))
        
        # Leer CSV actual
        rows = []
        fieldnames = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
        
        if page < 1 or page > len(rows):
            flash('Página inválida', 'error')
            return redirect(url_for('view_document_page', doc_name=doc_name, page=1))
        
        # Actualizar datos editables de la página actual
        row_index = page - 1
        rows[row_index]['folio'] = request.form.get('folio', '').strip()
        rows[row_index]['rut'] = request.form.get('rut', '').strip()
        rows[row_index]['fecha'] = request.form.get('fecha', '').strip()
        rows[row_index]['nombre'] = request.form.get('nombre', '').strip()
        
        # Guardar CSV actualizado
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        flash('Cambios guardados exitosamente', 'success')
        
    except Exception as e:
        flash(f'Error al guardar: {str(e)}', 'error')
    
    return redirect(url_for('view_document_page', doc_name=doc_name, page=page))

@app.route('/documents')
def documents():
    """Vista de documentos - Seleccionar PDFs de /input"""
    # Obtener lista de PDFs en /input
    pdf_files = []
    if os.path.exists('input'):
        pdf_files = [f for f in os.listdir('input') if f.lower().endswith('.pdf')]
    return render_template('documents.html', pdf_files=pdf_files)

@app.route('/extract')
def extract():
    """Extracción de datos - OCR de documentos procesados"""
    # Obtener documentos que tienen carpeta en /documentos
    processed_docs = []
    if os.path.exists('documentos'):
        processed_docs = [d for d in os.listdir('documentos') 
                         if os.path.isdir(os.path.join('documentos', d))]
    return render_template('extract.html', processed_docs=processed_docs)

@app.route('/process_pdf/<filename>')
def process_pdf(filename):
    """Procesar PDF - convertir a imágenes y crear CSV"""
    try:
        print(f"\n🎯 Solicitud de procesamiento recibida para: {filename}")
        
        # Verificar que el archivo existe
        pdf_path = os.path.join('input', filename)
        if not os.path.exists(pdf_path):
            print(f"❌ Error: El archivo {filename} no existe en /input")
            flash(f'Error: El archivo {filename} no se encuentra', 'error')
            return redirect(url_for('documents'))
        
        # Obtener nombre sin extensión
        pdf_name = get_pdf_name_without_extension(filename)
        print(f"📄 Nombre del documento: {pdf_name}")
        
        # Verificar si ya está procesado
        doc_folder = os.path.join('documentos', pdf_name)
        if os.path.exists(doc_folder):
            print(f"⚠️  El documento {pdf_name} ya ha sido procesado")
            flash(f'El documento {pdf_name} ya ha sido procesado', 'warning')
            return redirect(url_for('documents'))
        
        # Procesar el PDF
        print(f"🔄 Iniciando procesamiento...")
        success = process_pdf_to_images_and_csv(pdf_path, pdf_name)
        
        if success:
            print(f"🎉 Procesamiento exitoso!")
            flash(f'PDF {filename} procesado exitosamente', 'success')
        else:
            print(f"💥 Error en el procesamiento")
            flash(f'Error al procesar el PDF {filename}', 'error')
            
    except Exception as e:
        print(f"💥 Error inesperado: {str(e)}")
        flash(f'Error inesperado: {str(e)}', 'error')
    
    return redirect(url_for('documents'))

@app.route('/extract_data/<doc_name>')
def extract_data(doc_name):
    """Extraer datos con OCR del documento especificado"""
    try:
        print(f"\n🔍 Iniciando extracción de datos para: {doc_name}")
        
        # Verificar que el documento existe
        doc_folder = os.path.join('documentos', doc_name)
        if not os.path.exists(doc_folder):
            print(f"❌ Error: El documento {doc_name} no existe")
            flash(f'Error: El documento {doc_name} no se encuentra', 'error')
            return redirect(url_for('extract'))
        
        # Procesar extracción de datos
        print(f"🔄 Procesando OCR...")
        success = process_document_ocr(doc_name)
        
        if success:
            print(f"🎉 Extracción exitosa!")
            flash(f'Datos extraídos exitosamente de {doc_name}', 'success')
        else:
            print(f"💥 Error en la extracción")
            flash(f'Error al extraer datos de {doc_name}', 'error')
            
    except Exception as e:
        print(f"💥 Error inesperado: {str(e)}")
        flash(f'Error inesperado: {str(e)}', 'error')
    
    return redirect(url_for('extract'))

@app.route('/image/<doc_name>/<path:filename>')
def serve_image(doc_name, filename):
    """Servir imágenes de los documentos"""
    try:
        image_dir = os.path.join('documentos', doc_name)
        return send_from_directory(image_dir, filename)
    except Exception as e:
        print(f"Error sirviendo imagen: {e}")
        return "Imagen no encontrada", 404

if __name__ == '__main__':
    app.run(debug=True)
