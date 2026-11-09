import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from camera import carregar_url


class CameraConfigTest(unittest.TestCase):
    def test_env_file_and_environment_priority(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / '.env'
            url = 'rtsp://usuario:senha${LITERAL}#@example.test:554/cam?channel=1&subtype=0'
            arquivo.write_text(f"AUTOWEIGHT_CAMERA_URL='{url}'\n", encoding='utf-8')
            with patch.dict('os.environ', {}, clear=True):
                self.assertEqual(carregar_url(arquivo), url)
            with patch.dict('os.environ', {'AUTOWEIGHT_CAMERA_URL': 'rtsp://override.test'}):
                self.assertEqual(carregar_url(arquivo), 'rtsp://override.test')

    def test_missing_and_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / '.env'
            with patch.dict('os.environ', {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, 'AUTOWEIGHT_CAMERA_URL'):
                    carregar_url(arquivo)
                arquivo.write_text('AUTOWEIGHT_CAMERA_URL=https://example.test\n', encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'RTSP'):
                    carregar_url(arquivo)
