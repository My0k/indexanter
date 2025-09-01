import os
import csv
import shutil
from datetime import datetime
from pathlib import Path
try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        print("❌ PyMuPDF no está instalado")
        fitz = None

def extraer_fecha_componentes(fecha_str):
    """Extrae año y mes de la fecha"""
    try:
        if not fecha_str or fecha_str.strip() == '':
            return None, None
            
        # Intentar diferentes formatos de fecha
        formatos = ['%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y']
        
        for formato in formatos:
            try:
                fecha = datetime.strptime(fecha_str.strip(), formato)
                return fecha.year, fecha.month
            except ValueError:
                continue
        
        print(f"⚠️  No se pudo procesar fecha '{fecha_str}'")
        return None, None
        
    except Exception as e:
        print(f"❌ Error al procesar fecha '{fecha_str}': {e}")
        return None, None

def obtener_tipo_documento_nombre(tipo_num_str):
    """Convierte el número de tipo a nombre de documento"""
    try:
        if not tipo_num_str or tipo_num_str.strip() == '':
            return "sin_tipo"
            
        tipo_num = int(tipo_num_str.strip())
        tipos = {
            1: "egreso",
            2: "traspaso", 
            3: "ingreso",
            4: "voucher"
        }
        return tipos.get(tipo_num, f"tipo_{tipo_num}")
    except (ValueError, TypeError):
        return "sin_tipo"

def crear_directorio_si_no_existe(path):
    """Crea directorio si no existe"""
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"📁 Directorio creado: {path}")
        return True
    return False

def separar_pdfs_por_estructura(doc_name, carpeta_salida="pdfs_estructurados"):
    """
    Separa PDFs usando estructura: carpeta_salida/año/mes/tipo_documento/folio.pdf
    
    Args:
        doc_name (str): Nombre del documento procesado
        carpeta_salida (str): Carpeta base donde se creará la estructura
    
    Returns:
        dict: Resultado del procesamiento con estadísticas
    """
    
    if fitz is None:
        return {
            'success': False,
            'error': 'PyMuPDF no está disponible',
            'pdfs_creados': 0
        }
    
    try:
        # Rutas base
        doc_folder = os.path.join('documentos', doc_name)
        csv_path = os.path.join(doc_folder, f"{doc_name}.csv")
        pdfs_separados_folder = os.path.join(doc_folder, 'pdfs_separados')
        
        # Verificar que existan los archivos necesarios
        if not os.path.exists(csv_path):
            return {
                'success': False,
                'error': f'No se encontró el CSV: {csv_path}',
                'pdfs_creados': 0
            }
        
        if not os.path.exists(pdfs_separados_folder):
            return {
                'success': False,
                'error': f'No hay PDFs separados. Primero ejecuta la separación normal.',
                'pdfs_creados': 0
            }
        
        # Leer datos del CSV
        print(f"📖 Leyendo datos de {csv_path}")
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Crear carpeta base
        base_salida = os.path.join(carpeta_salida, doc_name)
        crear_directorio_si_no_existe(carpeta_salida)
        crear_directorio_si_no_existe(base_salida)
        
        # Estadísticas
        pdfs_creados = 0
        pdfs_sin_fecha = 0
        pdfs_sin_tipo = 0
        errores = []
        
        print(f"🔄 Procesando {len(rows)} registros...")
        
        # Procesar cada fila del CSV
        for i, row in enumerate(rows):
            try:
                folio = row.get('folio', '').strip()
                fecha_str = row.get('fecha', '').strip()
                tipo_documento_num = row.get('tipo_documento', '').strip()
                ocultar = row.get('ocultar', 'NO').strip()
                
                # Saltar si no hay folio o está marcado para ocultar
                if not folio or ocultar == 'SI':
                    continue
                
                # Extraer año y mes de la fecha
                año, mes = extraer_fecha_componentes(fecha_str)
                if año is None or mes is None:
                    año, mes = 'sin_fecha', '00'
                    pdfs_sin_fecha += 1
                    print(f"⚠️  Folio {folio}: Sin fecha válida, usando carpeta 'sin_fecha'")
                
                # Obtener tipo de documento
                tipo_documento = obtener_tipo_documento_nombre(tipo_documento_num)
                if tipo_documento == 'sin_tipo':
                    pdfs_sin_tipo += 1
                    print(f"⚠️  Folio {folio}: Sin tipo válido, usando carpeta 'sin_tipo'")
                
                # Crear estructura de directorios: base/año/mes/tipo_documento/
                if año == 'sin_fecha':
                    directorio_destino = os.path.join(base_salida, 'sin_fecha', tipo_documento)
                else:
                    directorio_destino = os.path.join(base_salida, str(año), f"{mes:02d}", tipo_documento)
                
                crear_directorio_si_no_existe(directorio_destino)
                
                # Buscar PDF original en pdfs_separados
                pdf_original = os.path.join(pdfs_separados_folder, f"{folio}.pdf")
                pdf_destino = os.path.join(directorio_destino, f"{folio}.pdf")
                
                if os.path.exists(pdf_original):
                    # Copiar PDF a la nueva estructura
                    shutil.copy2(pdf_original, pdf_destino)
                    pdfs_creados += 1
                    print(f"✅ Copiado: {folio}.pdf -> {año}/{mes:02d if isinstance(mes, int) else mes}/{tipo_documento}/")
                else:
                    error_msg = f"PDF no encontrado para folio {folio}"
                    errores.append(error_msg)
                    print(f"❌ {error_msg}")
                
            except Exception as e:
                error_msg = f"Error procesando fila {i+1}: {str(e)}"
                errores.append(error_msg)
                print(f"❌ {error_msg}")
                continue
        
        # Crear reporte de resultados
        resultado = {
            'success': True,
            'pdfs_creados': pdfs_creados,
            'pdfs_sin_fecha': pdfs_sin_fecha,
            'pdfs_sin_tipo': pdfs_sin_tipo,
            'errores': errores,
            'carpeta_salida': base_salida
        }
        
        print(f"\n🎉 ===== RESUMEN =====")
        print(f"✅ PDFs creados: {pdfs_creados}")
        print(f"⚠️  PDFs sin fecha: {pdfs_sin_fecha}")
        print(f"⚠️  PDFs sin tipo: {pdfs_sin_tipo}")
        print(f"❌ Errores: {len(errores)}")
        print(f"📁 Carpeta de salida: {base_salida}")
        
        return resultado
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error general: {str(e)}',
            'pdfs_creados': 0
        }

def listar_estructura_creada(carpeta_base):
    """Lista la estructura de carpetas creada"""
    if not os.path.exists(carpeta_base):
        print(f"❌ La carpeta {carpeta_base} no existe")
        return
    
    print(f"\n📁 Estructura creada en: {carpeta_base}")
    for root, dirs, files in os.walk(carpeta_base):
        level = root.replace(carpeta_base, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            if file.endswith('.pdf'):
                print(f"{subindent}{file}")

# Función de ejemplo para uso independiente
def main():
    """Función principal para uso independiente"""
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python separador_pdf.py <nombre_documento>")
        print("Ejemplo: python separador_pdf.py ARCHIVADOR_00000001")
        return
    
    doc_name = sys.argv[1]
    resultado = separar_pdfs_por_estructura(doc_name)
    
    if resultado['success']:
        print("✅ Separación completada exitosamente")
        listar_estructura_creada(resultado['carpeta_salida'])
    else:
        print(f"❌ Error: {resultado['error']}")

if __name__ == "__main__":
    main()
