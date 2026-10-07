import importlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import main
from camera import Camera, salvar_jpeg, carregar_contingencia, MARCADOR_CONTINGENCIA


class PesagensTest(unittest.TestCase):
    def setUp(self):
        self.app = importlib.reload(main)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app.PASTA_DADOS = Path(self.temp.name)
        self.frame = np.zeros((60, 80, 3), dtype=np.uint8)
        self.app.camera = Mock()
        self.app.camera.foto_recente.return_value = self.frame
        self.clock = 100
        self.patcher = patch.object(main.time, 'time', side_effect=lambda: self.clock)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def weigh(self, weight, seconds=0):
        self.clock += seconds
        self.app.ultima_tentativa_foto = float('-inf')
        self.app.avaliar_pesagem(weight)

    def test_stability_replacement_and_next_truck(self):
        self.weigh(2000)
        self.weigh(2020, 2)
        self.assertEqual(list(self.app.PASTA_DADOS.iterdir()), [])
        self.weigh(2000, 1)
        first = self.app.ultima_foto
        self.assertTrue(first.name.endswith('-2020kg.jpg'))
        self.assertEqual(cv2.imread(str(first)).shape, self.frame.shape)
        self.weigh(2000, 20)
        self.assertEqual(len(list(self.app.PASTA_DADOS.iterdir())), 1)
        self.weigh(2500)
        self.weigh(2500, 5)
        self.assertFalse(first.exists())
        self.assertTrue(self.app.ultima_foto.name.endswith('-2500kg.jpg'))
        self.weigh(0)
        self.weigh(3000)
        self.weigh(3000, 5)
        self.assertEqual(len(list(self.app.PASTA_DADOS.glob('*.jpg'))), 2)

    def assert_manga(self, photo):
        image = cv2.imread(str(photo))
        original = carregar_contingencia()
        self.assertEqual(image.shape, original.shape)
        self.assertLess(np.abs(image.astype(float) - original.astype(float)).mean(), 5)
        self.assertIn(MARCADOR_CONTINGENCIA, photo.read_bytes()[:256])

    def test_away_only_signals_first_successful_record_per_truck(self):
        self.app.sirene = Mock()
        self.assertTrue(self.app.alternar_modo_ausente())
        self.weigh(2000)
        with patch.object(main, 'salvar_jpeg', side_effect=OSError('disk full')):
            self.weigh(2000, 5)
        self.app.sirene.acionar.assert_not_called()
        self.weigh(2000, 3)
        self.app.sirene.acionar.assert_called_once_with()
        self.weigh(2500)
        self.weigh(2500, 5)
        self.app.sirene.acionar.assert_called_once_with()
        self.weigh(0)
        self.weigh(3000)
        self.weigh(3000, 5)
        self.assertEqual(self.app.sirene.acionar.call_count, 2)

    def test_enabling_after_first_photo_does_not_signal_replacement(self):
        self.app.sirene = Mock()
        self.weigh(2000)
        self.weigh(2000, 5)
        self.app.sirene.acionar.assert_not_called()
        self.app.alternar_modo_ausente()
        self.weigh(2500)
        self.weigh(2500, 5)
        self.app.sirene.acionar.assert_not_called()

    def test_away_signals_successful_contingency_record(self):
        self.app.sirene = Mock()
        self.app.alternar_modo_ausente()
        self.app.camera.foto_recente.return_value = None
        self.weigh(2000)
        self.weigh(2000, 5)
        self.app.sirene.acionar.assert_called_once_with()

    def test_camera_failure_saves_manga(self):
        self.app.camera.foto_recente.return_value = None
        self.weigh(2000)
        self.weigh(2000, 5)
        self.assertTrue(self.app.pesagem_registrada)
        photo = self.app.ultima_foto
        self.assertTrue(photo.name.endswith('-2000kg.jpg'))
        self.assert_manga(photo)
        self.app.camera.foto_recente.return_value = self.frame
        self.weigh(2000, 3)
        self.assertTrue(self.app.pesagem_registrada)
        self.assertEqual(list(self.app.PASTA_DADOS.iterdir()), [photo])

    def test_encoding_failure_saves_manga(self):
        real_save = main.salvar_jpeg

        def fail_original(frame, dest, **kwargs):
            if frame is self.frame:
                raise ValueError('invalid frame')
            real_save(frame, dest, **kwargs)

        self.weigh(2000)
        with patch.object(main, 'salvar_jpeg', side_effect=fail_original):
            self.weigh(2000, 5)
        self.assertTrue(self.app.pesagem_registrada)
        self.assert_manga(self.app.ultima_foto)

    def test_capture_exception_saves_manga(self):
        self.app.camera.foto_recente.side_effect = RuntimeError('camera error')
        self.weigh(2000)
        self.weigh(2000, 5)
        self.assertTrue(self.app.pesagem_registrada)
        self.assert_manga(self.app.ultima_foto)

    def test_missing_fallback_retries_without_registering(self):
        self.app.camera.foto_recente.return_value = None
        self.weigh(2000)
        with patch.object(main, 'carregar_contingencia', side_effect=OSError('missing')):
            self.weigh(2000, 5)
        self.assertFalse(self.app.pesagem_registrada)
        self.assertEqual(list(self.app.PASTA_DADOS.iterdir()), [])
        self.weigh(2000, 3)
        self.assertTrue(self.app.pesagem_registrada)
        self.assert_manga(self.app.ultima_foto)

    def test_failed_replacement_preserves_previous_photo(self):
        self.weigh(2000)
        self.weigh(2000, 5)
        original = self.app.ultima_foto
        self.weigh(2500)
        with patch.object(main, 'salvar_jpeg', side_effect=OSError('disk full')):
            self.weigh(2500, 5)
        self.assertTrue(original.exists())
        self.assertEqual(self.app.ultima_pesagem_registrada_kg, 2000)
        self.weigh(2500, 3)
        self.assertFalse(original.exists())

    def test_oscillation_restarts_stability(self):
        self.weigh(2000)
        self.weigh(2500, 4)
        self.weigh(2500, 1)
        self.assertFalse(self.app.pesagem_registrada)
        self.weigh(2500, 4)
        self.assertTrue(self.app.pesagem_registrada)

    def test_stale_frame_is_rejected(self):
        cam = Camera('rtsp://unused')
        cam._frame = self.frame
        cam._received = time.monotonic() - 3
        self.assertIsNone(cam.foto_recente())
        cam._received = time.monotonic()
        self.assertIsNotNone(cam.foto_recente())

    def test_jpeg_failure_leaves_no_partial_record(self):
        dest = self.app.PASTA_DADOS / 'record.jpg'
        with patch.object(Path, 'replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                salvar_jpeg(self.frame, dest)
        self.assertEqual(list(self.app.PASTA_DADOS.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
