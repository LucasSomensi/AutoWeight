import tempfile
import threading
import tkinter as tk
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from camera import Camera, salvar_jpeg
from gui import Painel, ultimo_registro


class GuiTest(unittest.TestCase):
    def test_camera_status_expires(self):
        camera = Camera('rtsp://unused')
        self.assertFalse(camera.conectada())
        camera._frame = np.zeros((2, 2, 3), dtype=np.uint8)
        camera._received = time.monotonic()
        self.assertTrue(camera.conectada())
        camera._received -= 3
        self.assertFalse(camera.conectada())

    def test_latest_record_ignores_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            pasta = Path(folder)
            for name in ['teste.jpg', '2026-09-07-12-00-00-000000-2000kg.jpg',
                         '2026-09-07-13-00-00-000000-3000kg.jpg']:
                (pasta / name).touch()
            caminho, horario, peso = ultimo_registro(pasta)
            self.assertEqual(peso, 3000)
            self.assertEqual(horario.hour, 13)

    def test_panel_updates_and_closes(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '2026-09-07-13-00-00-000000-3000kg.jpg'
            salvar_jpeg(np.zeros((60, 80, 3), dtype=np.uint8), path)
            estado = dict(peso=3200, recebido=time.monotonic(), foto=path,
                          hora=datetime(2026, 9, 7, 13), peso_foto=3000,
                          foto_branca=False, mensagem='Pesagem registrada.')
            app = SimpleNamespace(PASTA_DADOS=Path(folder), parar=threading.Event(),
                                  camera=Mock(), obter_estado=lambda: estado)
            app.executar = lambda verbose: app.parar.wait(2)
            app.camera.conectada.return_value = True
            painel = Painel(root, app)
            self.assertEqual(painel.peso.cget('text'), '3.200')
            self.assertIn('Conectada', painel.camera.cget('text'))
            self.assertIn('3.000 kg', painel.detalhes.cget('text'))
            self.assertIsNotNone(painel.imagem)
            estado['recebido'] -= 4
            app.camera.conectada.return_value = False
            painel.atualizar()
            self.assertEqual(painel.peso.cget('text'), '—')
            self.assertIn('Sem imagem', painel.camera.cget('text'))
            estado.update(foto_branca=True)
            painel.carregar_foto(path, estado['hora'], 3000, True)
            self.assertIn('contingência', painel.aviso.cget('text'))
            app.parar.set()
            painel.worker.join(3)
            self.assertFalse(painel.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
