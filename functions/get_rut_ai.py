#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_rut_ai.py - Integrado con el proyecto de indexación

Extrae RUTs y nombres de imágenes de comprobantes usando OpenAI Vision API
"""

import sys
import os
import re
import json
import base64
import configparser
import math
from io import BytesIO
from pathlib import Path
import pandas as pd

import cv2
import numpy as np
from PIL import Image

# OpenAI SDK (2025)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def read_api_key(config_path="config.conf"):
    """Lee la API key desde config.conf"""
    cfg = configparser.ConfigParser()
    if not os.path.exists(config_path):
        print(f"❌ No se encontró {config_path}")
        return None
    cfg.read(config_path)
    try:
        key = cfg.get("OPENAI", "key").strip()
        if not key:
            print("❌ La clave de OpenAI está vacía en config.conf")
            return None
        return key
    except Exception as e:
        print(f"❌ Error leyendo config.conf: {e}")
        return None


def detect_table_region(image_path):
    """
    Detecta automáticamente la región de la tabla en la imagen
    Busca rectángulos grandes que podrían contener tablas
    """
    try:
        # Cargar imagen
        if isinstance(image_path, str):
            data = np.fromfile(image_path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        else:
            img = image_path
            
        if img is None:
            return None
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Detectar bordes
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        # Encontrar contornos
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Buscar el contorno más grande que sea aproximadamente rectangular
        min_area = (img.shape[0] * img.shape[1]) * 0.1  # Al menos 10% de la imagen
        
        best_contour = None
        best_area = 0
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > min_area and area > best_area:
                # Aproximar a polígono
                epsilon = 0.02 * cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, epsilon, True)
                
                # Si tiene 4 vértices (rectángulo aproximado)
                if len(approx) == 4:
                    best_contour = approx
                    best_area = area
        
        if best_contour is not None:
            return best_contour.reshape(-1, 2).tolist()
        
        # Si no encuentra tabla, usar región central como fallback
        h, w = img.shape[:2]
        margin_x, margin_y = w // 6, h // 6
        return [
            [margin_x, margin_y],
            [w - margin_x, margin_y], 
            [w - margin_x, h - margin_y],
            [margin_x, h - margin_y]
        ]
        
    except Exception as e:
        print(f"❌ Error detectando región de tabla: {e}")
        return None


def order_points(pts):
    """
    Ordena los 4 puntos en el orden:
    [top-left, top-right, bottom-right, bottom-left]
    """
    pts = np.array(pts, dtype="float32")
    s = pts.sum(axis=1)               # x + y
    diff = np.diff(pts, axis=1)       # y - x

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype="float32")


def four_point_transform(image, pts):
    """Aplica transformación de perspectiva para enderezar la región"""
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    # calcular ancho/alto max del nuevo plano
    widthA = math.dist(br, bl)
    widthB = math.dist(tr, tl)
    maxWidth = int(round(max(widthA, widthB)))

    heightA = math.dist(tr, br)
    heightB = math.dist(tl, bl)
    maxHeight = int(round(max(heightA, heightB)))

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]],
        dtype="float32"
    )

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def pil_to_jpeg_bytes(pil_img, quality=90):
    """Convierte imagen PIL a bytes JPEG"""
    buf = BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def ensure_json(text):
    """
    Intenta recuperar un JSON válido desde la respuesta.
    """
    # si ya es JSON
    try:
        data = json.loads(text)
        # Normaliza a lista de objetos
        if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
            return json.dumps(data["items"], ensure_ascii=False)
        if isinstance(data, list):
            return json.dumps(data, ensure_ascii=False)
        # Si viene dict con otra llave, intenta encontrar una lista dentro
        for v in (data.values() if isinstance(data, dict) else []):
            if isinstance(v, list):
                return json.dumps(v, ensure_ascii=False)
        # último recurso: devuélvelo como objeto
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        pass

    # intenta extraer bloque JSON con regex
    m = re.search(r"(\[.*\]|\{.*\})", text, flags=re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                return json.dumps(data["items"], ensure_ascii=False)
            if isinstance(data, list):
                return json.dumps(data, ensure_ascii=False)
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            pass

    # si todo falla, envuelve como error
    return json.dumps({"error": "Respuesta no JSON", "raw": text[:500]}, ensure_ascii=False)


def build_prompt():
    """Construye el prompt para OpenAI"""
    return (
        "Analiza la imagen que contiene una TABLA con RUTs y nombres de personas.\n\n"
        "Instrucciones estrictas:\n"
        "- Devuelve SOLO la información de la TABLA (ignora timbres, sellos, encabezados, pie de página o cualquier otro texto fuera de la tabla).\n"
        "- Entrega un JSON con una lista de objetos: [{\"rut\":\"..\",\"nombre\":\"..\"}, ...]\n"
        "- Si el nombre no está visible en la celda de la tabla, omítelo o usa \"\".\n"
        "- Normaliza RUT chileno con puntos y guion (ej: 12.345.678-9). DV puede ser K.\n"
        "- Normaliza NOMBRES en mayúsculas, sin tildes si vienen inconsistentes.\n"
        "- No incluyas comentarios, no incluyas explicaciones.\n"
        "- Si no hay tabla o no hay datos válidos, devuelve una lista vacía []."
    )


def call_openai_vision(api_key, pil_cropped, model="gpt-4o-mini"):
    """Llama a OpenAI Vision API para extraer datos de la tabla"""
    if OpenAI is None:
        raise RuntimeError("Paquete 'openai' no disponible. Instala con: pip install openai")

    client = OpenAI(api_key=api_key)
    img_b64 = base64.b64encode(pil_to_jpeg_bytes(pil_cropped, quality=92)).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{img_b64}"

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Eres un extractor OCR que SOLO devuelve JSON válido."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_prompt()},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ],
        )
        content = resp.choices[0].message.content.strip()
        # Forzamos a que sea lista pura
        content = ensure_json(content)
        return content
    except Exception as e:
        return json.dumps({"error": f"OpenAI error: {str(e)}"}, ensure_ascii=False)


def extract_ruts_from_image(image_path, api_key):
    """
    Extrae RUTs y nombres de una imagen de comprobante
    
    Args:
        image_path (str): Path a la imagen
        api_key (str): API key de OpenAI
    
    Returns:
        str: JSON string con los datos extraídos
    """
    try:
        print(f"  🔍 Analizando imagen: {os.path.basename(image_path)}")
        
        # Cargar imagen
        data = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            return json.dumps({"error": "No se pudo leer la imagen"}, ensure_ascii=False)
        
        # Detectar región de tabla automáticamente
        pts = detect_table_region(img)
        if not pts or len(pts) != 4:
            print(f"  ⚠️  No se pudo detectar tabla, usando imagen completa")
            pil_crop = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        else:
            print(f"  ✅ Región de tabla detectada")
            # Recorte por perspectiva
            warped = four_point_transform(img, pts)
            pil_crop = Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))
        
        # Llamar a OpenAI Vision
        result_json = call_openai_vision(api_key, pil_crop, model="gpt-4o-mini")
        
        # Validar que sea JSON válido
        try:
            parsed = json.loads(result_json)
            # Si es dict con items, devuélvelo como lista
            if isinstance(parsed, dict) and "items" in parsed and isinstance(parsed["items"], list):
                parsed = parsed["items"]
            # Fuerza formato esperado: lista de objetos
            if isinstance(parsed, dict):
                parsed = [parsed]
            
            print(f"  ✅ Datos extraídos: {len(parsed)} registros")
            return json.dumps(parsed, ensure_ascii=False)
            
        except Exception:
            print(f"  ❌ Respuesta no válida de OpenAI")
            return json.dumps({"error": "Respuesta no válida de OpenAI"}, ensure_ascii=False)
        
    except Exception as e:
        print(f"  ❌ Error procesando imagen: {str(e)}")
        return json.dumps({"error": f"Error procesando imagen: {str(e)}"}, ensure_ascii=False)


def procesar_entregable_con_ai(entregable_num):
    """
    Procesa el entregable especificado agregando datos de IA para comprobantes
    
    Args:
        entregable_num (int): Número del entregable a procesar
    
    Returns:
        dict: Resultado del procesamiento
    """
    try:
        # Verificar que existe el entregable
        entregable_folder = os.path.join("ENTREGABLES", f"ENTREGABLE{entregable_num:02d}")
        if not os.path.exists(entregable_folder):
            return {
                'success': False,
                'error': f'No se encontró el entregable {entregable_num:02d}'
            }
        
        # Buscar el Excel consolidado
        excel_path = os.path.join(entregable_folder, f"CONSOLIDADO_ENTREGABLE{entregable_num:02d}.xlsx")
        if not os.path.exists(excel_path):
            return {
                'success': False,
                'error': f'No se encontró el Excel consolidado: {excel_path}'
            }
        
        # Leer API key
        api_key = read_api_key("config.conf")
        if not api_key:
            return {
                'success': False,
                'error': 'No se pudo leer la API key de OpenAI desde config.conf'
            }
        
        print(f"🤖 Iniciando procesamiento con IA para ENTREGABLE{entregable_num:02d}")
        print(f"📊 Leyendo Excel: {excel_path}")
        
        # Leer Excel
        df = pd.read_excel(excel_path)
        
        # Agregar columna para datos de IA si no existe
        if 'datos_ai_ruts' not in df.columns:
            df['datos_ai_ruts'] = ''
        
        comprobantes_procesados = 0
        errores = 0
        
        # Procesar cada fila que tenga folio (es comprobante)
        for index, row in df.iterrows():
            folio = str(row.get('folio', '')).strip()
            path_img_completo = str(row.get('path_img_completo', '')).strip()
            
            # Solo procesar si tiene folio (es comprobante) y path de imagen
            if folio and path_img_completo and os.path.exists(path_img_completo):
                print(f"\n🔄 Procesando comprobante {folio} ({comprobantes_procesados + 1})")
                
                # Extraer datos con IA
                datos_ai = extract_ruts_from_image(path_img_completo, api_key)
                
                # Guardar en el DataFrame
                df.at[index, 'datos_ai_ruts'] = datos_ai
                comprobantes_procesados += 1
                
                print(f"  📝 Datos guardados: {datos_ai[:100]}...")
                
            elif folio and not path_img_completo:
                print(f"  ⚠️  Comprobante {folio}: No se encontró path de imagen")
                df.at[index, 'datos_ai_ruts'] = json.dumps({"error": "Imagen no encontrada"}, ensure_ascii=False)
                errores += 1
            elif folio and not os.path.exists(path_img_completo):
                print(f"  ⚠️  Comprobante {folio}: Imagen no existe en {path_img_completo}")
                df.at[index, 'datos_ai_ruts'] = json.dumps({"error": "Archivo de imagen no existe"}, ensure_ascii=False)
                errores += 1
        
        # Guardar Excel actualizado
        print(f"\n💾 Guardando Excel actualizado...")
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
                adjusted_width = min(max_length + 2, 80)  # Aumentado para la columna de JSON
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        # Actualizar resumen
        resumen_path = os.path.join(entregable_folder, "RESUMEN.txt")
        if os.path.exists(resumen_path):
            with open(resumen_path, 'a', encoding='utf-8') as f:
                f.write(f"\n\nPROCESAMIENTO CON IA:\n")
                f.write(f"Fecha procesamiento IA: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Comprobantes procesados: {comprobantes_procesados}\n")
                f.write(f"Errores: {errores}\n")
                f.write(f"Columna agregada: datos_ai_ruts (JSON con RUTs y nombres extraídos)\n")
        
        resultado = {
            'success': True,
            'entregable_num': entregable_num,
            'comprobantes_procesados': comprobantes_procesados,
            'errores': errores,
            'excel_path': excel_path
        }
        
        print(f"\n🎉 ===== PROCESAMIENTO IA COMPLETADO =====")
        print(f"📋 Comprobantes procesados: {comprobantes_procesados}")
        print(f"❌ Errores: {errores}")
        print(f"📊 Excel actualizado: {excel_path}")
        
        return resultado
        
    except Exception as e:
        print(f"❌ Error en procesamiento con IA: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e),
            'comprobantes_procesados': 0,
            'errores': 0
        }


# Función principal para uso independiente
def main():
    """Función principal para uso independiente"""
    if len(sys.argv) < 2:
        print("Uso: python get_rut_ai.py <numero_entregable>")
        print("Ejemplo: python get_rut_ai.py 1")
        return
    
    try:
        entregable_num = int(sys.argv[1])
        resultado = procesar_entregable_con_ai(entregable_num)
        
        if resultado['success']:
            print("✅ Procesamiento completado exitosamente")
        else:
            print(f"❌ Error: {resultado['error']}")
            
    except ValueError:
        print("❌ El número de entregable debe ser un entero")


if __name__ == "__main__":
    main()
