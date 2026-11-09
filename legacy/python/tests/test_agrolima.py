import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from agrolima import Estabilidade, Publicador, carregar_configuracao


class ApiTest(unittest.TestCase):
    def test_config_file_and_environment(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / '.env'
            arquivo.write_text('AGROLIMA_BASE_URL=example.up.railway.app/\nAGROLIMA_API_KEY=segredo', encoding='utf-8')
            with patch.dict('os.environ', {}, clear=True):
                self.assertEqual(carregar_configuracao(arquivo),
                                 ('https://example.up.railway.app/api/balancas/1/peso', 'segredo'))
            with patch.dict('os.environ', {'AGROLIMA_BASE_URL': 'http://inseguro'}):
                with self.assertRaises(ValueError):
                    carregar_configuracao(arquivo)

    def test_stability_zero_negative_gap_and_oscillation(self):
        enviar = Mock()
        filtro = Estabilidade(enviar)
        with patch('agrolima.time.monotonic') as clock:
            for t, peso in [(0, 500), (0.5, 520)]:
                clock.return_value = t
                filtro.avaliar(peso)
            enviar.assert_not_called()
            clock.return_value = 1
            filtro.avaliar(500)
            enviar.assert_called_once_with(520)
            for t, peso in [(2, 520), (4, 500), (5, 500),
                            (6, 500), (7, -1), (8, 20), (9, 0),
                            (11, 0), (13, 0), (14, 0)]:
                clock.return_value = t
                filtro.avaliar(peso)
            self.assertEqual([c.args[0] for c in enviar.call_args_list], [520, 0])
            for t, peso in [(15, 100), (20, 100), (22, 100), (24, 100), (25, 100)]:
                clock.return_value = t
                filtro.avaliar(peso)
            self.assertEqual(enviar.call_count, 3)

    def executar_publicador(self, resultados, pesos=None):
        concluido = threading.Event()
        mensagens = []
        def informar(mensagem):
            mensagens.append(mensagem)
            concluido.set()
        pub = Publicador('https://example.test/api/balancas/1/peso', 'segredo', informar)
        sessao = Mock()
        def post(*args, **kwargs):
            resultado = resultados.pop(0)
            if isinstance(resultado, Exception):
                raise resultado
            resposta = Mock(status_code=resultado)
            resposta.__enter__ = Mock(return_value=resposta)
            resposta.__exit__ = Mock(return_value=False)
            return resposta
        sessao.post.side_effect = post
        with patch('agrolima.requests.Session') as construtor:
            construtor.return_value.__enter__.return_value = sessao
            pub.publicar(500)
            pub.start()
            try:
                self.assertTrue(concluido.wait(3))
                if pesos:
                    for peso in pesos:
                        pub.publicar(peso)
                return pub, sessao, mensagens
            finally:
                pub.close()

    def test_payload_success(self):
        pub, sessao, _ = self.executar_publicador([200])
        self.assertEqual(pub.ultimo_enviado, 500)
        parametros = sessao.post.call_args.kwargs
        self.assertEqual(parametros['json'], {'peso_kg': 500})
        self.assertEqual(parametros['headers']['Authorization'], 'Bearer segredo')
        self.assertEqual(parametros['timeout'], (5, 15))
        self.assertFalse(parametros['allow_redirects'])

    def test_permanent_errors_block(self):
        for codigo in (400, 401, 302, 413):
            pub, sessao, _ = self.executar_publicador([codigo], [600])
            self.assertTrue(pub.bloqueado)
            self.assertEqual(sessao.post.call_count, 1)

    def test_transient_errors_remain_pending_and_hide_secrets(self):
        for erro in (503, requests.Timeout('segredo')):
            pub, _, mensagens = self.executar_publicador([erro])
            self.assertFalse(pub.bloqueado)
            self.assertEqual(pub.pendente, 500)
            self.assertNotIn('segredo', str(mensagens))

    def test_invalid_values(self):
        pub = Publicador('https://example.test', 'segredo')
        for peso in (-1, True, 1.5, '5', 2147483648):
            with self.assertRaises(ValueError):
                pub.publicar(peso)

    def test_retry_uses_latest_weight_and_deduplicates(self):
        concluido = threading.Event()
        pub = Publicador('https://example.test', 'segredo')
        enviados = []
        def post(*args, **kwargs):
            enviados.append(kwargs['json']['peso_kg'])
            if len(enviados) == 1:
                pub.publicar(700)
                raise requests.Timeout()
            resposta = Mock(status_code=200)
            resposta.__enter__ = Mock(return_value=resposta)
            resposta.__exit__ = Mock(return_value=False)
            return resposta
        def informar(mensagem):
            if 'enviado' in mensagem:
                concluido.set()
        pub.informar = informar
        with patch('agrolima.requests.Session') as construtor:
            sessao = construtor.return_value.__enter__.return_value
            sessao.post.side_effect = post
            pub.publicar(500)
            pub.start()
            try:
                self.assertTrue(concluido.wait(4))
                pub.publicar(700)
                # Aguarda o worker consumir a repetição, sem uma nova requisição.
                with pub.condicao:
                    self.assertEqual(pub.ultimo_enviado, 700)
                self.assertEqual(enviados, [500, 700])
            finally:
                pub.close()
