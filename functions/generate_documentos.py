import os
import csv
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
