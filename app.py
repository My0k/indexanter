from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, send_file
import os
import csv
from datetime import datetime
from pdf2image import convert_from_path
import logging
from functions.generate_documentos import process_pdf_to_images_and_csv, get_pdf_name_without_extension, generar_entregable_consolidado
from functions.extraer_datos import process_document_ocr
import zipfile
from io import BytesIO
import shutil
from functions.separador_pdf import separar_pdfs_por_estructura
import pandas as pd
import glob

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
    
    # Obtener entregables existentes
    entregables_existentes = []
    if os.path.exists('ENTREGABLES'):
        for folder in os.listdir('ENTREGABLES'):
            if folder.startswith('ENTREGABLE') and os.path.isdir(os.path.join('ENTREGABLES', folder)):
                try:
                    entregable_path = os.path.join('ENTREGABLES', folder)
                    
                    # Extraer número
                    num = int(folder.replace('ENTREGABLE', ''))
                    
                    # Obtener fecha de creación
                    fecha_creacion = datetime.fromtimestamp(os.path.getctime(entregable_path)).strftime('%Y-%m-%d %H:%M')
                    
                    # Contar PDFs
                    pdfs_folder = os.path.join(entregable_path, 'PDFS')
                    num_pdfs = 0
                    if os.path.exists(pdfs_folder):
                        num_pdfs = len([f for f in os.listdir(pdfs_folder) if f.endswith('.pdf')])
                    
                    # Leer resumen si existe
                    resumen_path = os.path.join(entregable_path, 'RESUMEN.txt')
                    num_registros = 0
                    if os.path.exists(resumen_path):
                        with open(resumen_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            import re
                            match = re.search(r'Registros en Excel: (\d+)', content)
                            if match:
                                num_registros = int(match.group(1))
                    
                    entregables_existentes.append({
                        'numero': num,
                        'nombre': folder,
                        'fecha_creacion': fecha_creacion,
                        'num_pdfs': num_pdfs,
                        'num_registros': num_registros
                    })
                except (ValueError, OSError):
                    continue
    
    # Ordenar por número descendente (más reciente primero)
    entregables_existentes.sort(key=lambda x: x['numero'], reverse=True)
    
    return render_template('index.html', 
                         processed_docs=processed_docs,
                         entregables_existentes=entregables_existentes)

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
            fieldnames = list(reader.fieldnames)
            rows = list(reader)

        # Verificar si existen las nuevas columnas y añadirlas si no existen
        new_columns = ['ocultar', 'estado', 'tipo_documento', 'nota']
        for col in new_columns:
            if col not in fieldnames:
                fieldnames.append(col)
                # Añadir valor por defecto a todas las filas existentes
                for row in rows:
                    if col not in row:
                        if col == 'ocultar':
                            row[col] = 'NO'
                        elif col in ['estado', 'tipo_documento', 'nota']:
                            row[col] = ''  # Vacío por defecto

        if page < 1 or page > len(rows):
            flash('Página inválida', 'error')
            return redirect(url_for('view_document_page', doc_name=doc_name, page=1))
        
        # Actualizar datos editables de la página actual
        row_index = page - 1
        rows[row_index]['folio'] = request.form.get('folio', '').strip()
        rows[row_index]['rut'] = request.form.get('rut', '').strip()
        rows[row_index]['fecha'] = request.form.get('fecha', '').strip()
        rows[row_index]['nombre'] = request.form.get('nombre', '').strip()
        rows[row_index]['ocultar'] = request.form.get('ocultar', 'NO').strip()
        rows[row_index]['estado'] = request.form.get('estado', '').strip()
        rows[row_index]['tipo_documento'] = request.form.get('tipo_documento', '').strip()
        rows[row_index]['nota'] = request.form.get('nota', '').strip()  # NUEVO CAMPO
        
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
        # Normalizar el nombre del archivo reemplazando backslashes por forward slashes
        filename = filename.replace('\\', '/')
        # Obtener el directorio base y el nombre del archivo
        base_dir = os.path.abspath(os.path.join('documentos', doc_name))
        # Usar os.path.basename para obtener solo el nombre del archivo
        file_name = os.path.basename(filename)
        # Obtener el subdirectorio si existe
        sub_dir = os.path.dirname(filename)
        # Construir la ruta completa del directorio
        image_dir = os.path.join(base_dir, sub_dir) if sub_dir else base_dir
        
        print(f"Directorio de imagen: {image_dir}")
        print(f"Nombre de archivo: {file_name}")
        
        return send_from_directory(image_dir, file_name)
    except Exception as e:
        print(f"Error sirviendo imagen: {e}")
        print(f"doc_name: {doc_name}")
        print(f"filename: {filename}")
        return "Imagen no encontrada", 404

@app.route('/download_csv/<doc_name>')
def download_csv(doc_name):
    """Descargar CSV del documento"""
    try:
        doc_folder = os.path.join('documentos', doc_name)
        csv_path = os.path.join(doc_folder, f"{doc_name}.csv")
        
        if not os.path.exists(csv_path):
            flash(f'Error: No se encontró el CSV para {doc_name}', 'error')
            return redirect(url_for('index'))
        
        # Enviar archivo con nombre descriptivo
        return send_file(
            csv_path,
            as_attachment=True,
            download_name=f"cuadratura_{doc_name}.csv",
            mimetype='text/csv'
        )
        
    except Exception as e:
        flash(f'Error al descargar CSV: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/descargar_documentos/<doc_name>')
def descargar_documentos(doc_name):
    """Vista para separar y descargar PDFs por folio"""
    try:
        doc_folder = os.path.join('documentos', doc_name)
        csv_path = os.path.join(doc_folder, f"{doc_name}.csv")
        
        if not os.path.exists(csv_path):
            flash(f'Error: No se encontró el CSV para {doc_name}', 'error')
            return redirect(url_for('index'))
        
        # Leer datos del CSV para analizar folios
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Analizar estructura de folios
        folio_groups = []
        current_group = None
        
        for i, row in enumerate(rows):
            folio = row.get('folio', '').strip()
            page_num = i + 1
            
            if folio:  # Nueva sección con folio
                if current_group:
                    current_group['end_page'] = page_num - 1
                    folio_groups.append(current_group)
                
                current_group = {
                    'folio': folio,
                    'start_page': page_num,
                    'end_page': page_num,
                    'pages': [page_num]
                }
            elif current_group:  # Página sin folio, añadir al grupo actual
                current_group['end_page'] = page_num
                current_group['pages'].append(page_num)
        
        # Añadir el último grupo
        if current_group:
            folio_groups.append(current_group)
        
        # Verificar si ya existen PDFs generados
        pdfs_folder = os.path.join(doc_folder, 'pdfs_separados')
        pdfs_generados = []
        if os.path.exists(pdfs_folder):
            for folio_group in folio_groups:
                pdf_name = f"{folio_group['folio']}.pdf"
                pdf_path = os.path.join(pdfs_folder, pdf_name)
                if os.path.exists(pdf_path):
                    size_mb = round(os.path.getsize(pdf_path) / (1024 * 1024), 2)
                    pdfs_generados.append({
                        'name': pdf_name,
                        'folio': folio_group['folio'],
                        'pages': len(folio_group['pages']),
                        'size_mb': size_mb,
                        'path': pdf_path
                    })
        
        return render_template('descargar_documentos.html',
                             doc_name=doc_name,
                             folio_groups=folio_groups,
                             pdfs_generados=pdfs_generados,
                             total_pdfs=len(folio_groups))
                             
    except Exception as e:
        flash(f'Error al cargar datos: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/separar_pdfs/<doc_name>')
def separar_pdfs(doc_name):
    """Generar PDFs separados por folio"""
    try:
        # Verificar que PyMuPDF esté disponible
        if fitz is None:
            flash('Error: PyMuPDF no está disponible', 'error')
            return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        # Buscar el PDF original en input/
        pdf_original = None
        if os.path.exists('input'):
            for file in os.listdir('input'):
                if file.lower().endswith('.pdf') and doc_name.lower() in file.lower():
                    pdf_original = os.path.join('input', file)
                    break
        
        if not pdf_original or not os.path.exists(pdf_original):
            flash(f'Error: No se encontró el PDF original para {doc_name}', 'error')
            return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        doc_folder = os.path.join('documentos', doc_name)
        csv_path = os.path.join(doc_folder, f"{doc_name}.csv")
        
        # Leer estructura de folios
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Analizar grupos por folio
        folio_groups = []
        current_group = None
        
        for i, row in enumerate(rows):
            folio = row.get('folio', '').strip()
            ocultar = row.get('ocultar', 'NO').strip()
            page_num = i + 1
            
            # Solo procesar páginas que NO están marcadas para ocultar
            if ocultar != 'SI':
                if folio:
                    if current_group:
                        folio_groups.append(current_group)
                    
                    current_group = {
                        'folio': folio,
                        'pages': [page_num]
                    }
                elif current_group:
                    current_group['pages'].append(page_num)
        
        if current_group:
            folio_groups.append(current_group)
        
        # Crear carpeta para PDFs separados
        pdfs_folder = os.path.join(doc_folder, 'pdfs_separados')
        os.makedirs(pdfs_folder, exist_ok=True)
        
        # Abrir PDF original con manejo de errores
        try:
            doc_pdf = fitz.open(pdf_original)
        except AttributeError:
            try:
                doc_pdf = fitz.Document(pdf_original)
            except AttributeError:
                flash('Error: No se puede abrir el PDF con PyMuPDF', 'error')
                return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        pdfs_creados = 0
        
        # Generar PDF para cada grupo de folio
        for group in folio_groups:
            folio = group['folio']
            pages = group['pages']
            
            # Crear nuevo PDF
            try:
                new_pdf = fitz.open()
            except AttributeError:
                new_pdf = fitz.Document()
            
            for page_num in pages:
                # PyMuPDF usa índices base 0
                page_index = page_num - 1
                if page_index < doc_pdf.page_count:
                    new_pdf.insert_pdf(doc_pdf, from_page=page_index, to_page=page_index)
            
            # Guardar PDF
            pdf_name = f"{folio}.pdf"
            pdf_path = os.path.join(pdfs_folder, pdf_name)
            new_pdf.save(pdf_path)
            new_pdf.close()
            pdfs_creados += 1
            
            print(f"✅ Creado {pdf_name} con {len(pages)} páginas")
        
        doc_pdf.close()
        
        flash(f'Se generaron {pdfs_creados} PDFs separados exitosamente', 'success')
        
    except Exception as e:
        flash(f'Error al separar PDFs: {str(e)}', 'error')
    
    return redirect(url_for('descargar_documentos', doc_name=doc_name))

@app.route('/separar_pdfs_estructura/<doc_name>')
def separar_pdfs_estructura(doc_name):
    """Generar PDFs con estructura de carpetas por año/mes/tipo"""
    try:
        resultado = separar_pdfs_por_estructura(doc_name)
        
        if resultado['success']:
            flash(f'PDFs organizados exitosamente: {resultado["pdfs_creados"]} archivos creados', 'success')
            if resultado['pdfs_sin_fecha'] > 0:
                flash(f'Advertencia: {resultado["pdfs_sin_fecha"]} PDFs sin fecha válida', 'warning')
            if resultado['pdfs_sin_tipo'] > 0:
                flash(f'Advertencia: {resultado["pdfs_sin_tipo"]} PDFs sin tipo válido', 'warning')
        else:
            flash(f'Error al organizar PDFs: {resultado["error"]}', 'error')
            
    except Exception as e:
        flash(f'Error inesperado: {str(e)}', 'error')
    
    return redirect(url_for('descargar_documentos', doc_name=doc_name))

@app.route('/download_pdf/<doc_name>/<pdf_name>')
def download_pdf(doc_name, pdf_name):
    """Descargar PDF individual"""
    try:
        pdfs_folder = os.path.join('documentos', doc_name, 'pdfs_separados')
        pdf_path = os.path.join(pdfs_folder, pdf_name)
        
        if not os.path.exists(pdf_path):
            flash(f'Error: No se encontró el PDF {pdf_name}', 'error')
            return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f"{doc_name}_{pdf_name}",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        flash(f'Error al descargar PDF: {str(e)}', 'error')
        return redirect(url_for('descargar_documentos', doc_name=doc_name))

@app.route('/download_all_pdfs/<doc_name>')
def download_all_pdfs(doc_name):
    """Descargar todos los PDFs en un ZIP con estructura de carpetas"""
    try:
        # Primero generar la estructura organizada
        print(f"🔄 Generando estructura organizada para {doc_name}")
        resultado = separar_pdfs_por_estructura(doc_name, carpeta_salida="temp_zip")
        
        if not resultado['success']:
            flash(f'Error al organizar PDFs: {resultado["error"]}', 'error')
            return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        # Verificar que se crearon PDFs
        if resultado['pdfs_creados'] == 0:
            flash('No hay PDFs para descargar', 'warning')
            return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        # Crear ZIP en memoria con estructura de carpetas
        memory_file = BytesIO()
        carpeta_estructurada = os.path.join("temp_zip", doc_name)
        
        if not os.path.exists(carpeta_estructurada):
            flash('Error: No se pudo crear la estructura de carpetas', 'error')
            return redirect(url_for('descargar_documentos', doc_name=doc_name))
        
        print(f"📦 Creando ZIP con estructura desde: {carpeta_estructurada}")
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Recorrer toda la estructura de carpetas
            for root, dirs, files in os.walk(carpeta_estructurada):
                for file in files:
                    if file.endswith('.pdf'):
                        # Ruta completa del archivo
                        file_path = os.path.join(root, file)
                        
                        # Ruta relativa dentro del ZIP (sin "temp_zip/")
                        # Ejemplo: "ARCHIVADOR_00000001/2019/12/egreso/19120264.pdf"
                        relative_path = os.path.relpath(file_path, "temp_zip")
                        
                        # Añadir al ZIP manteniendo la estructura
                        zf.write(file_path, relative_path)
                        print(f"  ✅ Añadido al ZIP: {relative_path}")
        
        # Limpiar carpeta temporal
        try:
            import shutil
            shutil.rmtree("temp_zip")
            print("🧹 Carpeta temporal eliminada")
        except Exception as e:
            print(f"⚠️  No se pudo eliminar carpeta temporal: {e}")
        
        memory_file.seek(0)
        
        # Nombre del ZIP con información adicional
        zip_filename = f"{doc_name}_estructurado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        print(f"📥 Enviando ZIP: {zip_filename} ({resultado['pdfs_creados']} PDFs)")
        
        return send_file(
            memory_file,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
        
    except Exception as e:
        print(f"❌ Error al crear ZIP estructurado: {str(e)}")
        flash(f'Error al crear ZIP: {str(e)}', 'error')
        return redirect(url_for('descargar_documentos', doc_name=doc_name))

@app.route('/generar_entregable')
def generar_entregable():
    """Generar entregable consolidado con todos los documentos"""
    try:
        print(f"\n🎯 Iniciando generación de entregable consolidado...")
        
        resultado = generar_entregable_consolidado()
        
        if resultado['success']:
            flash(f'Entregable {resultado["entregable_num"]:02d} generado exitosamente: {resultado["pdfs_copiados"]} PDFs, {resultado["registros_excel"]} registros', 'success')
            flash(f'Carpeta: {resultado["entregable_folder"]}', 'info')
        else:
            flash(f'Error al generar entregable: {resultado["error"]}', 'error')
            
    except Exception as e:
        flash(f'Error inesperado: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/download_entregable/<int:entregable_num>')
def download_entregable(entregable_num):
    """Descargar entregable completo como ZIP"""
    try:
        entregable_folder = os.path.join("ENTREGABLES", f"ENTREGABLE{entregable_num:02d}")
        
        if not os.path.exists(entregable_folder):
            flash(f'Error: No se encontró el entregable {entregable_num:02d}', 'error')
            return redirect(url_for('index'))
        
        # Crear ZIP en memoria
        memory_file = BytesIO()
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Recorrer toda la carpeta del entregable
            for root, dirs, files in os.walk(entregable_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Ruta relativa dentro del ZIP
                    relative_path = os.path.relpath(file_path, "ENTREGABLES")
                    zf.write(file_path, relative_path)
        
        memory_file.seek(0)
        
        zip_filename = f"ENTREGABLE{entregable_num:02d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        return send_file(
            memory_file,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
        
    except Exception as e:
        flash(f'Error al descargar entregable: {str(e)}', 'error')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)