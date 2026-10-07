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
    def test_navigation_preserves_selection_and_follows_latest(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as folder:
            pasta = Path(folder)
            estado = dict(peso=None, recebido=None, foto=None, mensagem='Teste')
            app = SimpleNamespace(PASTA_DADOS=pasta, parar=threading.Event(),
                                  camera=None, obter_estado=lambda: estado,
                                  executar=lambda verbose: None)
            app.alternar_modo_ausente = lambda: estado.update(modo_ausente=not estado.get('modo_ausente', False))
            painel = Painel(root, app)
            painel.ausente.invoke()
            painel.atualizar()
            self.assertIn('ATIVADO', painel.ausente.cget('text'))
            painel.ausente.invoke()
            painel.atualizar()
            self.assertIn('DESATIVADO', painel.ausente.cget('text'))
            self.assertEqual(painel.anterior.cget('state'), 'disabled')
            self.assertEqual(painel.proxima.cget('state'), 'disabled')

            def registrar(hora, peso):
                caminho = pasta / f'2026-09-07-{hora:02d}-00-00-000000-{peso}kg.jpg'
                salvar_jpeg(np.zeros((60, 80, 3), dtype=np.uint8), caminho)
                estado['foto'] = caminho
                painel.atualizar()
                return caminho

            primeira = registrar(10, 2000)
            self.assertEqual(painel.foto_atual, primeira)
            segunda = registrar(11, 3000)
            self.assertEqual(painel.foto_atual, segunda)
            painel.anterior.invoke()
            self.assertEqual(painel.foto_atual, primeira)
            self.assertIn('10:00:00', painel.detalhes.cget('text'))
            self.assertIn('2.000 kg', painel.detalhes.cget('text'))
            terceira = registrar(12, 4000)
            self.assertEqual(painel.foto_atual, primeira)
            self.assertEqual(painel.posicao.cget('text'), '1 / 3')
            self.assertEqual(painel.anterior.cget('state'), 'disabled')
            painel.proxima.invoke()
            self.assertEqual(painel.foto_atual, segunda)
            painel.proxima.invoke()
            self.assertEqual(painel.foto_atual, terceira)
            self.assertEqual(painel.proxima.cget('state'), 'disabled')
            terceira.unlink()
            substituta = registrar(13, 4500)
            self.assertEqual(painel.foto_atual, substituta)
            self.assertEqual(painel.posicao.cget('text'), '3 / 3')
            painel.worker.join(3)

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
            app.alternar_modo_ausente = Mock()
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
            salvar_jpeg(np.zeros((60, 80, 3), dtype=np.uint8), path, contingencia=True)
            painel.carregar_foto(path, estado['hora'], 3000)
            self.assertIn('mangá de contingência', painel.aviso.cget('text'))
            app.parar.set()
            painel.worker.join(3)
            self.assertFalse(painel.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
