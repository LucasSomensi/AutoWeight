"""Leitura contínua da câmera, sem bloquear a porta serial."""

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
import numpy as np
from dotenv import dotenv_values

IMAGEM_CONTINGENCIA = Path(__file__).resolve().parent / "assets" / "camera-indisponivel-manga.png"
MARCADOR_CONTINGENCIA = b"AutoWeight:contingencia:manga"


def carregar_contingencia():
    frame = cv2.imdecode(np.frombuffer(IMAGEM_CONTINGENCIA.read_bytes(), dtype=np.uint8),
                         cv2.IMREAD_COLOR)
    if frame is None:
        raise OSError("Imagem de contingência inválida.")
    return frame


def carregar_url(arquivo=None):
    arquivo = Path(arquivo) if arquivo is not None else Path(__file__).with_name(".env")
    valores = dotenv_values(arquivo, encoding="utf-8-sig", interpolate=False)
    url = os.environ.get("AUTOWEIGHT_CAMERA_URL", valores.get("AUTOWEIGHT_CAMERA_URL"))
    if not url:
        raise RuntimeError("Configure AUTOWEIGHT_CAMERA_URL no .env.")
    if not isinstance(url, str) or not url.startswith("rtsp://"):
        raise RuntimeError("A câmera precisa de uma URL RTSP válida.")
    return url


class Camera:
    def __init__(self, url):
        self.url = url
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._frame = None
        self._received = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=12)

    def foto_recente(self):
        with self._lock:
            if self._frame is None or time.monotonic() - self._received > 2:
                return None
            return self._frame.copy()

    def conectada(self):
        with self._lock:
            return self._frame is not None and time.monotonic() - self._received <= 2

    def _run(self):
        while not self._stop.is_set():
            cap = cv2.VideoCapture()
            try:
                cap.open(self.url, cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
                ])
                if cap.isOpened():
                    print("Câmera conectada.")
                while cap.isOpened() and not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    with self._lock:
                        self._frame = frame
                        self._received = time.monotonic()
            except cv2.error:
                pass
            finally:
                cap.release()
                with self._lock:
                    self._frame = None
            if not self._stop.is_set():
                print("Câmera indisponível. Tentando reconectar em 3 segundos.")
                self._stop.wait(3)


def salvar_jpeg(frame, destino, contingencia=False):
    """Publica somente um JPEG completo, inclusive em caminhos com acentos."""
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise OSError("Não foi possível codificar a foto.")
    dados = encoded.tobytes()
    if contingencia:
        comentario = b"\xff\xfe" + (len(MARCADOR_CONTINGENCIA) + 2).to_bytes(2, "big") + MARCADOR_CONTINGENCIA
        dados = dados[:2] + comentario + dados[2:]
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".jpg.tmp")
    try:
        with temporario.open("xb") as arquivo:
            arquivo.write(dados)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)
