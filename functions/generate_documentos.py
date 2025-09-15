import os
import csv
import pandas as pd
import glob
import shutil
from datetime import datetime

try:
    import pymupdf as fitz  # Importación moderna de PyMuPDF
except ImportError:
    try:
        import fitz  # Fallback a la importación tradicional
    except ImportError:
        print("❌ PyMuPDF no está instalado")
        fitz = None

from PIL import Image
from pathlib import Path

def save_jpg_from_pixmap(pix, out_path, quality=90):
    """
    Guarda un pixmap de PyMuPDF como JPG
    """
    # Convertir a RGB si tiene canal alpha
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    
    # Convertir a PIL Image y guardar
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img.save(out_path, format="JPEG", quality=quality, optimize=True)

def ensure_dir(path):
    """
    Crea directorio si no existe
    """
    path.mkdir(parents=True, exist_ok=True)

def process_pdf_to_images_and_csv(pdf_path, pdf_name):
    """
    Procesa un PDF página por página, generando imágenes y actualizando CSV incrementalmente.
    
    Args:
        pdf_path (str): Ruta completa al archivo PDF
        pdf_name (str): Nombre del PDF sin extensión
    
    Returns:
        bool: True si el procesamiento fue exitoso, False en caso contrario
    """
    csv_file = None
    doc = None
    
    try:
        # Verificar que PyMuPDF esté disponible
        if fitz is None:
            print("❌ PyMuPDF no está disponible")
            return False
            
        print(f"🚀 Iniciando procesamiento del PDF: {pdf_name}")
        
        # 1. Crear estructura de carpetas
        base_folder = Path('documentos') / pdf_name
        images_folder = base_folder / 'imagenes'
        
        print(f"📁 Creando carpeta base: {base_folder}")
        ensure_dir(base_folder)
        
        print(f"📁 Creando carpeta de imágenes: {images_folder}")
        ensure_dir(images_folder)
        
        # 2. Preparar CSV
        csv_filename = f"{pdf_name}.csv"
        csv_path = base_folder / csv_filename
        
        print(f"📊 Preparando archivo CSV: {csv_filename}")
        
        # Verificar si necesitamos escribir headers
        write_header = not csv_path.exists()
        
        # Abrir CSV en modo append
        csv_file = open(csv_path, "a", newline="", encoding="utf-8")
        csv_writer = csv.writer(csv_file)
        
        # Escribir headers si es un archivo nuevo
        if write_header:
            fieldnames = ['numero_hoja', 'nombre_img', 'path_img', 'ocultar']
            print(f"✏️  Escribiendo headers: {', '.join(fieldnames)}")
            csv_writer.writerow(fieldnames)
        
        # 3. Abrir PDF con PyMuPDF
        print(f"📖 Abriendo PDF: {pdf_path}")
        print(f"🔍 Verificando métodos disponibles en fitz: {[attr for attr in dir(fitz) if 'open' in attr.lower()]}")
        
        # Intentar diferentes formas de abrir el PDF
        try:
            doc = fitz.open(pdf_path)
        except AttributeError:
            try:
                doc = fitz.Document(pdf_path)
            except AttributeError:
                print("❌ No se puede encontrar método para abrir PDF en fitz")
                return False
        
        n_pages = len(doc)
        print(f"📄 PDF cargado exitosamente. Total de páginas: {n_pages}")
        
        # 4. Procesar página por página
        for i in range(n_pages):
            page_num = i + 1
            
            # Formatear número con ceros a la izquierda (0001, 0002, etc.)
            image_number = f"{page_num:04d}"
            image_filename = f"{image_number}.jpg"
            image_path = images_folder / image_filename
            
            print(f"🔄 Procesando página {page_num}/{n_pages}: {image_filename}")
            
            # Cargar página y convertir a imagen
            try:
                page = doc[i]  # Indexing directo
            except:
                page = doc.load_page(i)  # Método tradicional
            
            # Matriz para alta calidad (~200 DPI)
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Guardar imagen
            print(f"💾 Guardando imagen: {image_filename}")
            save_jpg_from_pixmap(pix, image_path)
            
            # Preparar datos para CSV (path relativo desde la carpeta del documento)
            relative_path = os.path.join('imagenes', image_filename)
            
            # Escribir fila al CSV inmediatamente
            csv_row = [page_num, image_filename, relative_path, 'NO']
            csv_writer.writerow(csv_row)
            print(f"📝 Fila agregada al CSV: Hoja {page_num} -> {image_filename}")
            
            # Liberar memoria del pixmap
            pix = None
            
            print(f"✅ Página {page_num} completada")
        
        print(f"🎉 Procesamiento completado exitosamente!")
        print(f"📋 Resumen:")
        print(f"   - Carpeta creada: {base_folder}")
        print(f"   - Imágenes generadas: {n_pages} archivos en {images_folder}")
        print(f"   - CSV actualizado: {csv_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error durante el procesamiento: {str(e)}")
        import traceback
        print(f"📋 Detalles del error:")
        traceback.print_exc()
        return False
        
    finally:
        # Cerrar archivos
        if csv_file:
            csv_file.close()
            print(f"🔒 Archivo CSV cerrado")
        if doc:
            doc.close()
            print(f"🔒 Documento PDF cerrado")

def get_pdf_name_without_extension(filename):
    """
    Obtiene el nombre del PDF sin la extensión .pdf
    
    Args:
        filename (str): Nombre del archivo con extensión
    
    Returns:
        str: Nombre sin extensión
    """
    return os.path.splitext(filename)[0]

def check_pdf_dependencies():
    """
    Verifica que las dependencias necesarias estén instaladas
    """
    try:
        import pymupdf as fitz_test
        print("✅ PyMuPDF está disponible como 'pymupdf'")
        print(f"✅ Versión: {fitz_test.version}")
        return True
    except ImportError:
        try:
            import fitz as fitz_test
            print("✅ PyMuPDF está disponible como 'fitz'")
            if hasattr(fitz_test, 'version'):
                print(f"✅ Versión: {fitz_test.version}")
            print(f"🔍 Métodos disponibles: {[attr for attr in dir(fitz_test) if not attr.startswith('_')][:10]}")
            return True
        except ImportError:
            print("❌ Error: PyMuPDF no está instalado")
            print("   Instala con: pip install PyMuPDF")
            return False

def generar_entregable_consolidado():
    """
    Genera un entregable consolidado manteniendo estructura año/mes/tipo pero consolidando todas las cajas
    
    Returns:
        dict: Resultado del procesamiento
    """
    try:
        # Crear carpeta ENTREGABLE con numeración
        base_entregables = "ENTREGABLES"
        os.makedirs(base_entregables, exist_ok=True)
        
        # Encontrar el siguiente número disponible
        existing_folders = [d for d in os.listdir(base_entregables) 
                           if d.startswith("ENTREGABLE") and os.path.isdir(os.path.join(base_entregables, d))]
        
        next_num = 1
        if existing_folders:
            nums = []
            for folder in existing_folders:
                try:
                    num = int(folder.replace("ENTREGABLE", ""))
                    nums.append(num)
                except ValueError:
                    continue
            if nums:
                next_num = max(nums) + 1
        
        entregable_folder = os.path.join(base_entregables, f"ENTREGABLE{next_num:02d}")
        os.makedirs(entregable_folder, exist_ok=True)
        
        print(f"📁 Creando entregable: {entregable_folder}")
        
        # Lista para recopilar todos los datos
        consolidado_data = []
        documentos_procesados = 0
        pdfs_copiados = 0
        
        # Buscar todos los documentos procesados
        if os.path.exists('documentos'):
            for doc_name in os.listdir('documentos'):
                doc_path = os.path.join('documentos', doc_name)
                if not os.path.isdir(doc_path):
                    continue
                
                csv_path = os.path.join(doc_path, f"{doc_name}.csv")
                if not os.path.exists(csv_path):
                    continue
                
                print(f"🔄 Procesando documento: {doc_name}")
                documentos_procesados += 1
                
                # Leer CSV del documento
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                
                # Buscar PDFs en la estructura organizada (pdfs_estructurados)
                pdfs_estructurados_base = os.path.join("pdfs_estructurados", doc_name)
                
                if os.path.exists(pdfs_estructurados_base):
                    print(f"  📦 Copiando estructura de {pdfs_estructurados_base}")
                    
                    # Copiar toda la estructura manteniendo año/mes/tipo pero consolidando
                    for root, dirs, files in os.walk(pdfs_estructurados_base):
                        for file in files:
                            if file.endswith('.pdf'):
                                src_path = os.path.join(root, file)
                                
                                # Obtener la ruta relativa desde la base del documento
                                relative_path = os.path.relpath(root, pdfs_estructurados_base)
                                
                                # Crear la misma estructura en el entregable
                                dest_dir = os.path.join(entregable_folder, relative_path)
                                os.makedirs(dest_dir, exist_ok=True)
                                
                                dest_path = os.path.join(dest_dir, file)
                                
                                try:
                                    shutil.copy2(src_path, dest_path)
                                    pdfs_copiados += 1
                                    print(f"  ✅ Copiado: {relative_path}/{file}")
                                except Exception as e:
                                    print(f"  ❌ Error copiando {file}: {e}")
                
                # Procesar cada fila del CSV para el Excel consolidado
                for row in rows:
                    folio = row.get('folio', '').strip()
                    
                    # Buscar el PDF correspondiente en la estructura
                    pdf_path_entregable = ""
                    pdf_path_original = ""
                    
                    if folio:
                        # Buscar en la estructura copiada
                        for root, dirs, files in os.walk(entregable_folder):
                            for file in files:
                                if file == f"{folio}.pdf":
                                    # Path relativo desde la carpeta del entregable
                                    pdf_path_entregable = os.path.relpath(
                                        os.path.join(root, file), 
                                        entregable_folder
                                    ).replace('\\', '/')
                                    break
                            if pdf_path_entregable:
                                break
                        
                        # Path original en pdfs_estructurados
                        pdfs_estructurados_base = os.path.join("pdfs_estructurados", doc_name)
                        if os.path.exists(pdfs_estructurados_base):
                            for root, dirs, files in os.walk(pdfs_estructurados_base):
                                for file in files:
                                    if file == f"{folio}.pdf":
                                        pdf_path_original = os.path.join(root, file).replace('\\', '/')
                                        break
                                if pdf_path_original:
                                    break
                    
                    # Crear registro consolidado con toda la información
                    registro = {
                        'documento_origen': doc_name,
                        'numero_hoja': row.get('numero_hoja', ''),
                        'nombre_img': row.get('nombre_img', ''),
                        'path_img_relativo': row.get('path_img', ''),
                        'path_img_completo': os.path.join('documentos', doc_name, row.get('path_img', '')).replace('\\', '/'),
                        'folio': folio,
                        'rut': row.get('rut', ''),
                        'fecha': row.get('fecha', ''),
                        'nombre': row.get('nombre', ''),
                        'estado': row.get('estado', ''),
                        'estado_texto': obtener_estado_texto(row.get('estado', '')),
                        'tipo_documento': row.get('tipo_documento', ''),
                        'tipo_documento_texto': obtener_tipo_documento_texto(row.get('tipo_documento', '')),
                        'nota': row.get('nota', ''),
                        'ocultar': row.get('ocultar', 'NO'),
                        'q1': row.get('q1', ''),
                        'q2': row.get('q2', ''),
                        'pdf_path_entregable': pdf_path_entregable,
                        'pdf_path_original': pdf_path_original
                    }
                    
                    consolidado_data.append(registro)
        
        # Crear Excel consolidado
        if consolidado_data:
            df = pd.DataFrame(consolidado_data)
            excel_path = os.path.join(entregable_folder, f"CONSOLIDADO_ENTREGABLE{next_num:02d}.xlsx")
            
            # Crear el Excel con formato
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Consolidado', index=False)
                
                # Obtener worksheet para formatear
                worksheet = writer.sheets['Consolidado']
                
                # Ajustar ancho de columnas
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            print(f"📊 Excel consolidado creado: {excel_path}")
        
        # Crear archivo de resumen
        resumen_path = os.path.join(entregable_folder, "RESUMEN.txt")
        
        # Analizar estructura creada
        estructura_info = []
        for root, dirs, files in os.walk(entregable_folder):
            if files and any(f.endswith('.pdf') for f in files):
                pdf_count = len([f for f in files if f.endswith('.pdf')])
                relative_path = os.path.relpath(root, entregable_folder)
                if relative_path != ".":
                    estructura_info.append(f"  {relative_path}: {pdf_count} PDFs")
        
        with open(resumen_path, 'w', encoding='utf-8') as f:
            f.write(f"ENTREGABLE {next_num:02d}\n")
            f.write(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"ESTADÍSTICAS:\n")
            f.write(f"- Documentos procesados: {documentos_procesados}\n")
            f.write(f"- PDFs copiados: {pdfs_copiados}\n")
            f.write(f"- Registros en Excel: {len(consolidado_data)}\n\n")
            f.write(f"CONTENIDO:\n")
            f.write(f"- Estructura de carpetas por año/mes/tipo consolidada\n")
            f.write(f"- CONSOLIDADO_ENTREGABLE{next_num:02d}.xlsx: Excel maestro con todos los datos\n")
            f.write(f"- RESUMEN.txt: Este archivo\n\n")
            f.write(f"ESTRUCTURA DE CARPETAS:\n")
            for info in sorted(estructura_info):
                f.write(f"{info}\n")
            f.write(f"\nORIGEN DE PDFs:\n")
            f.write(f"Los PDFs provienen de pdfs_estructurados/ de todos los documentos,\n")
            f.write(f"manteniendo la estructura año/mes/tipo pero consolidados en un solo entregable.\n")
        
        resultado = {
            'success': True,
            'entregable_folder': entregable_folder,
            'entregable_num': next_num,
            'documentos_procesados': documentos_procesados,
            'pdfs_copiados': pdfs_copiados,
            'registros_excel': len(consolidado_data),
            'excel_path': excel_path,
            'resumen_path': resumen_path
        }
        
        print(f"\n🎉 ===== ENTREGABLE {next_num:02d} COMPLETADO =====")
        print(f"📁 Carpeta: {entregable_folder}")
        print(f"📊 Excel: {excel_path}")
        print(f"📄 PDFs: {pdfs_copiados} archivos con estructura año/mes/tipo")
        print(f"📋 Registros: {len(consolidado_data)}")
        print(f"📂 Estructura consolidada de {documentos_procesados} documentos")
        
        return resultado
        
    except Exception as e:
        print(f"❌ Error generando entregable: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e),
            'entregable_folder': '',
            'pdfs_copiados': 0,
            'registros_excel': 0
        }

def obtener_tipo_documento_texto(tipo_num_str):
    """Convierte el número de tipo a texto descriptivo"""
    try:
        if not tipo_num_str or tipo_num_str.strip() == '':
            return "Sin tipo"
            
        tipo_num = int(tipo_num_str.strip())
        tipos = {
            1: "Egreso",
            2: "Traspaso", 
            3: "Ingreso",
            4: "Voucher"
        }
        return tipos.get(tipo_num, f"Tipo {tipo_num}")
    except (ValueError, TypeError):
        return "Sin tipo"

def obtener_estado_texto(estado_num_str):
    """Convierte el número de estado a texto descriptivo"""
    try:
        if not estado_num_str or estado_num_str.strip() == '':
            return "Sin estado"
            
        estado_num = int(estado_num_str.strip())
        estados = {
            1: "Vigente",
            2: "Pendiente", 
            3: "Actualizado",
            4: "Nulo"
        }
        return estados.get(estado_num, f"Estado {estado_num}")
    except (ValueError, TypeError):
        return "Sin estado"
