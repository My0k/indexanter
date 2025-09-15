#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crop_and_extract_ruts.py

Uso:
  1) Con puntos por CLI (x,y en cualquier orden; se ordenan automáticamente):
     python3 crop_and_extract_ruts.py 0198.jpg 321,243 678,231 750,1004 295,1008

  2) Con archivo .pts (4 líneas "x,y"); mismo nombre que la imagen:
     # 0198.pts
     321,243
     678,231
     750,1004
     295,1008
     python3 crop_and_extract_ruts.py 0198.jpg

Salida:
  - Imprime SOLO un JSON en stdout con RUTs y nombres detectados en la TABLA.
    Ej: [{"rut":"12.345.678-9","nombre":"JUAN PEREZ"}, ...]

Requisitos:
  pip install opencv-python-headless pillow openai configparser
  config.conf con la API key en [OPENAI] key=...
"""

import sys
import os
import re
import json
import base64
import configparser
import math
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

# OpenAI SDK (2025)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def read_api_key(config_path="config.conf"):
    cfg = configparser.ConfigParser()
    if not os.path.exists(config_path):
        return None
    cfg.read(config_path)
    try:
        return cfg.get("OPENAI", "key").strip()
    except Exception:
        return None


def parse_point(s):
    m = re.match(r"^\s*(\d+)\s*,\s*(\d+)\s*$", s)
    if not m:
        raise ValueError(f"Punto inválido: {s}")
    return (int(m.group(1)), int(m.group(2)))


def load_points_from_pts(img_path):
    base, _ = os.path.splitext(img_path)
    pts_path = base + ".pts"
    if not os.path.exists(pts_path):
        return None
    pts = []
    with open(pts_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pts.append(parse_point(line))
    if len(pts) != 4:
        raise ValueError(f"{pts_path} debe tener exactamente 4 líneas 'x,y'")
    return pts


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
    buf = BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def ensure_json(text):
    """
    Intenta recuperar un JSON válido desde la respuesta.
    - Si viene como objeto {"items":[...]} lo transforma a lista [...], o viceversa.
    - Si viene texto con json embebido, lo extrae.
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
    return (
        "Analiza la imagen (que es un RECORTE del área de interés) que contiene "
        "una TABLA con RUTs y nombres.\n\n"
        "Instrucciones estrictas:\n"
        "- Devuelve SOLO la información de la TABLA (ignora timbres, sellos, encabezados, pie de página o cualquier otro texto fuera de la tabla).\n"
        "- Entrega un JSON **solo** con una lista de objetos: [{\"rut\":\"..\",\"nombre\":\"..\"}, ...]\n"
        "- Si el nombre no está visible en la celda de la tabla, omítelo o usa \"\".\n"
        "- Normaliza RUT chileno con puntos y guion (ej: 12.345.678-9). DV puede ser K.\n"
        "- Normaliza NOMBRES en mayúsculas, sin tildes si vienen inconsistentes.\n"
        "- No incluyas comentarios, no incluyas explicaciones, no envuelvas en una clave 'items': devuelve directamente la lista JSON."
    )


def call_openai_vision(api_key, pil_cropped, model="gpt-4o-mini"):
    if OpenAI is None:
        raise RuntimeError("Paquete 'openai' no disponible. Instala con: pip install openai")

    client = OpenAI(api_key=api_key)
    img_b64 = base64.b64encode(pil_to_jpeg_bytes(pil_cropped, quality=92)).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{img_b64}"

    # Usamos Chat Completions para compatibilidad amplia
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
        # Si vino como objeto, intentar convertir a lista si corresponde
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "items" in parsed:
                parsed = parsed["items"]
                content = json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
        return content
    except Exception as e:
        return json.dumps({"error": f"OpenAI error: {str(e)}"}, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Uso: python3 crop_and_extract_ruts.py <imagen.jpg> [x1,y1 x2,y2 x3,y3 x4,y4]"}, ensure_ascii=False))
        return

    img_path = sys.argv[1]
    if not os.path.exists(img_path):
        print(json.dumps({"error": f"No existe la imagen: {img_path}"} , ensure_ascii=False))
        return

    # Leer puntos (CLI o .pts)
    pts = None
    if len(sys.argv) == 6:
        try:
            pts = [parse_point(sys.argv[2]), parse_point(sys.argv[3]),
                   parse_point(sys.argv[4]), parse_point(sys.argv[5])]
        except Exception as e:
            print(json.dumps({"error": f"Puntos inválidos: {str(e)}"}, ensure_ascii=False))
            return
    else:
        try:
            pts = load_points_from_pts(img_path)
        except Exception as e:
            print(json.dumps({"error": f"Error leyendo .pts: {str(e)}"}, ensure_ascii=False))
            return

    if not pts or len(pts) != 4:
        print(json.dumps({"error": "Se requieren 4 puntos (por CLI o .pts)"}, ensure_ascii=False))
        return

    # Cargar imagen (con soporte a nombres no ASCII)
    data = np.fromfile(img_path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        print(json.dumps({"error": "No se pudo leer la imagen (¿archivo corrupto?)"}, ensure_ascii=False))
        return

    # Recorte por perspectiva
    try:
        warped = four_point_transform(img, pts)
    except Exception as e:
        print(json.dumps({"error": f"Fallo en transformada de perspectiva: {str(e)}"}, ensure_ascii=False))
        return

    # Convertir a PIL y realizar un prepro ligero (opcional: binarizar suave)
    pil_crop = Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))

    # (Opcional) pequeño sharpen/contraste si quisieras:
    # from PIL import ImageEnhance
    # pil_crop = ImageEnhance.Contrast(pil_crop).enhance(1.1)

    # Leer API key
    api_key = read_api_key("config.conf")
    if not api_key:
        print(json.dumps({"error": "No se encontró OPENAI.key en config.conf"}, ensure_ascii=False))
        return

    # Llamar a OpenAI Vision
    result_json = call_openai_vision(api_key, pil_crop, model="gpt-4o-mini")

    # Imprimir SOLO JSON
    try:
        # Validar que sea JSON y normalizar a lista
        parsed = json.loads(result_json)
        # Si es dict con items, devuélvelo como lista
        if isinstance(parsed, dict) and "items" in parsed and isinstance(parsed["items"], list):
            parsed = parsed["items"]
        # Fuerza formato esperado: lista de objetos
        if isinstance(parsed, dict):
            parsed = [parsed]
        print(json.dumps(parsed, ensure_ascii=False))
    except Exception:
        # Si no es JSON válido, imprime objeto de error
        print(json.dumps({"error": "Respuesta no válida de OpenAI", "raw": result_json[:500]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
