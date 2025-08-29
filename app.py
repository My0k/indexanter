from flask import Flask, render_template, request, redirect, url_for, flash
import os
import csv
from pdf2image import convert_from_path
import logging
from functions.generate_documentos import process_pdf_to_images_and_csv, get_pdf_name_without_extension

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
    return render_template('index.html')

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
    """Extraer datos con OCR (placeholder - no implementado aún)"""
    # TODO: Implementar extracción de datos
    return redirect(url_for('extract'))

if __name__ == '__main__':
    app.run(debug=True)
