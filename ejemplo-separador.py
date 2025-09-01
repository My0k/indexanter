import pandas as pd
import os
import shutil
from datetime import datetime
import glob
import pytesseract
from PIL import Image
import fitz  # PyMuPDF
import io

def listar_archivos_excel():
    """Lista archivos Excel disponibles y permite seleccionar uno"""
    archivos_excel = glob.glob("*.xls") + glob.glob("*.xlsx")
    
    if not archivos_excel:
        print("No se encontraron archivos Excel en el directorio actual.")
        return None
    
    print("\nArchivos Excel disponibles:")
    for i, archivo in enumerate(archivos_excel, 1):
        print(f"{i}. {archivo}")
    
    while True:
        try:
            seleccion = int(input("\nSeleccione el número del archivo Excel: "))
            if 1 <= seleccion <= len(archivos_excel):
                return archivos_excel[seleccion - 1]
            else:
                print("Número inválido. Intente nuevamente.")
        except ValueError:
            print("Por favor ingrese un número válido.")

def obtener_tipo_documento(tipo_num):
    """Convierte el número de tipo a nombre de documento"""
    tipos = {
        1: "egreso",
        2: "traspaso", 
        3: "ingreso"
    }
    return tipos.get(tipo_num, f"tipo_{tipo_num}")

def extraer_fecha_componentes(fecha_str):
    """Extrae año y mes de la fecha"""
    try:
        # Intentar diferentes formatos de fecha
        formatos = ['%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d']
        
        for formato in formatos:
            try:
                fecha = datetime.strptime(fecha_str, formato)
                return fecha.year, fecha.month
            except ValueError:
                continue
        
        # Si no funciona ningún formato, intentar parse automático
        fecha = pd.to_datetime(fecha_str)
        return fecha.year, fecha.month
        
    except Exception as e:
        print(f"Error al procesar fecha '{fecha_str}': {e}")
        return None, None

def crear_directorio_si_no_existe(path):
    """Crea directorio si no existe"""
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"Directorio creado: {path}")

def aplicar_ocr_a_pdf(path_pdf):
    """Aplica OCR al PDF y retorna el texto extraído"""
    try:
        # Abrir el PDF
        doc = fitz.open(path_pdf)
        texto_completo = ""
        
        print(f"  Aplicando OCR a {os.path.basename(path_pdf)} ({len(doc)} páginas)...")
        
        for num_pagina in range(len(doc)):
            # Convertir página a imagen
            page = doc.load_page(num_pagina)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Aumentar resolución para mejor OCR
            img_data = pix.tobytes("png")
            
            # Convertir a PIL Image
            img = Image.open(io.BytesIO(img_data))
            
            # Aplicar OCR
            texto_pagina = pytesseract.image_to_string(img, lang='spa')
            texto_completo += f"\n--- Página {num_pagina + 1} ---\n"
            texto_completo += texto_pagina
            
        doc.close()
        return texto_completo.strip()
        
    except Exception as e:
        print(f"    Error aplicando OCR a {path_pdf}: {e}")
        return ""

def guardar_texto_ocr(texto, path_pdf_destino):
    """Guarda el texto OCR en un archivo .txt junto al PDF"""
    try:
        # Crear nombre del archivo de texto
        base_name = os.path.splitext(path_pdf_destino)[0]
        archivo_txt = f"{base_name}_ocr.txt"
        
        # Guardar texto
        with open(archivo_txt, 'w', encoding='utf-8') as f:
            f.write(texto)
        
        print(f"    Texto OCR guardado: {os.path.basename(archivo_txt)}")
        return archivo_txt
        
    except Exception as e:
        print(f"    Error guardando texto OCR: {e}")
        return None

def procesar_pdfs():
    """Función principal para procesar los PDFs"""
    
    # Seleccionar archivo Excel
    archivo_excel = listar_archivos_excel()
    if not archivo_excel:
        return
    
    # Pedir nombre de caja
    nombre_caja = input("\nIngrese el nombre de la caja de salida: ").strip()
    if not nombre_caja:
        print("El nombre de la caja no puede estar vacío.")
        return
    
    try:
        # Leer el archivo Excel
        print(f"\nProcesando archivo: {archivo_excel}")
        df = pd.read_excel(archivo_excel)
        
        # Verificar columnas requeridas
        columnas_requeridas = ['pdf', 'nombre_pdf', 'path_pdf', 'folio', 'fecha', 'rut', 'nombre', 'estado', 'tipo']
        columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]
        
        if columnas_faltantes:
            print(f"Error: Faltan las siguientes columnas en el Excel: {columnas_faltantes}")
            return
        
        # Crear directorio base de salida
        base_salida = f"pdfs_salida/{nombre_caja}"
        crear_directorio_si_no_existe("pdfs_salida")
        crear_directorio_si_no_existe(base_salida)
        
        # Lista para el Excel de salida
        resultados = []
        
        print(f"\nProcesando {len(df)} registros...")
        
        for index, row in df.iterrows():
            try:
                # Extraer información
                path_original = row['path_pdf']
                folio = row['folio']
                fecha_str = str(row['fecha'])
                tipo_num = int(row['tipo'])
                rut = row['rut']
                nombre = row['nombre']
                estado = row['estado']
                
                # Obtener año y mes
                año, mes = extraer_fecha_componentes(fecha_str)
                if año is None or mes is None:
                    print(f"Saltando registro {index + 1}: No se pudo procesar la fecha '{fecha_str}'")
                    continue
                
                # Obtener tipo de documento
                tipo_documento = obtener_tipo_documento(tipo_num)
                
                # Crear estructura de directorios
                directorio_destino = f"{base_salida}/{año}/{mes:02d}/{tipo_documento}"
                crear_directorio_si_no_existe(directorio_destino)
                
                # Nombre del archivo destino
                archivo_destino = f"{directorio_destino}/{folio}.pdf"
                nuevo_path = f"pdfs_salida/{nombre_caja}/{año}/{mes:02d}/{tipo_documento}/{folio}.pdf"
                
                # Copiar archivo si existe
                if os.path.exists(path_original):
                    shutil.copy2(path_original, archivo_destino)
                    print(f"Copiado: {path_original} -> {archivo_destino}")
                    
                    # Aplicar OCR al PDF copiado
                    print(f"  Procesando OCR para folio {folio}...")
                    texto_ocr = aplicar_ocr_a_pdf(archivo_destino)
                    
                    if texto_ocr:
                        archivo_txt = guardar_texto_ocr(texto_ocr, archivo_destino)
                    
                else:
                    print(f"Advertencia: No se encontró el archivo {path_original}")
                
                # Agregar a resultados
                resultados.append({
                    'año': año,
                    'mes': mes,
                    'tipodocumento': tipo_documento,
                    'folio': folio,
                    'rut': rut,
                    'nombre': nombre,
                    'estado': estado,
                    'nuevo_path': nuevo_path
                })
                
            except Exception as e:
                print(f"Error procesando registro {index + 1}: {e}")
                continue
        
        # Crear Excel de salida
        if resultados:
            df_salida = pd.DataFrame(resultados)
            archivo_salida = f"resultado_{nombre_caja}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            df_salida.to_excel(archivo_salida, index=False)
            print(f"\nExcel de salida creado: {archivo_salida}")
            print(f"Registros procesados exitosamente: {len(resultados)}")
        else:
            print("No se procesó ningún registro exitosamente.")
            
    except Exception as e:
        print(f"Error general: {e}")

if __name__ == "__main__":
    print("=== Separador de PDFs con OCR ===")
    print("Nota: Se aplicará OCR a cada PDF y se guardará el texto extraído")
    procesar_pdfs()