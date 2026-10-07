"""Publicação assíncrona do último peso relevante da balança 1."""

import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import dotenv_values

LOG = logging.getLogger(__name__)
TRANSITORIOS = {500, 502, 503, 504}


class Estabilidade:
    def __init__(self, publicar, segundos=1, oscilacao=20):
        self.publicar = publicar
        self.segundos, self.oscilacao = segundos, oscilacao
        self.reset()

    def reset(self):
        self.candidato = None
        self.inicio = None
        self.recebido = None
        self.maximo = None
        self.publicado = False

    def avaliar(self, peso):
        agora = time.monotonic()
        if type(peso) is not int or not 0 <= peso <= 2147483647:
            self.reset()
            return
        if self.recebido is not None and agora - self.recebido > 3:
            self.reset()
        self.recebido = agora
        if (self.candidato is None or abs(peso - self.candidato) > self.oscilacao
                or (peso == 0) != (self.candidato == 0)):
            self.candidato, self.maximo, self.inicio = peso, peso, agora
            self.publicado = False
            return
        self.maximo = max(self.maximo, peso)
        if not self.publicado and agora - self.inicio >= self.segundos:
            self.publicar(self.maximo)
            self.publicado = True


def carregar_configuracao(arquivo=None):
    arquivo = Path(arquivo) if arquivo is not None else Path(__file__).with_name(".env")
    valores = dotenv_values(arquivo, encoding="utf-8-sig", interpolate=False)
    url = (os.environ.get("AGROLIMA_BASE_URL", valores.get("AGROLIMA_BASE_URL")) or "").strip().rstrip("/")
    chave = os.environ.get("AGROLIMA_API_KEY", valores.get("AGROLIMA_API_KEY")) or ""
    if not url and not chave:
        return None
    if url and "://" not in url:
        url = "https://" + url
    partes = urlsplit(url)
    if (partes.scheme != "https" or not partes.hostname or partes.username
            or partes.password or partes.query or partes.fragment
            or partes.path or not chave or any(c.isspace() for c in chave)):
        raise ValueError("Configure AGROLIMA_BASE_URL com a origem HTTPS e AGROLIMA_API_KEY sem espaços.")
    return url + "/api/balancas/1/peso", chave


class Publicador:
    def __init__(self, url, chave, informar=lambda mensagem: None):
        self.url, self.chave = url, chave
        self.informar = informar
        self.condicao = threading.Condition()
        self.pendente = None
        self.ultimo_enviado = None
        self.encerrado = False
        self.bloqueado = False
        self.thread = threading.Thread(target=self._executar, daemon=True)

    def start(self):
        self.thread.start()

    def publicar(self, peso):
        if type(peso) is not int or not 0 <= peso <= 2147483647:
            raise ValueError("Peso deve ser inteiro entre 0 e 2147483647.")
        with self.condicao:
            if not self.encerrado and not self.bloqueado and peso != self.pendente:
                self.pendente = peso
                self.condicao.notify_all()

    def close(self):
        with self.condicao:
            self.encerrado = True
            self.condicao.notify_all()
        if self.thread.ident is not None:
            self.thread.join(timeout=1)

    def _executar(self):
        atraso = 1
        with requests.Session() as sessao:
            while True:
                with self.condicao:
                    self.condicao.wait_for(lambda: self.encerrado or (
                        not self.bloqueado and self.pendente is not None))
                    if self.encerrado:
                        return
                    peso = self.pendente
                    if peso == self.ultimo_enviado:
                        self.pendente = None
                        continue
                codigo = None
                erro = ""
                try:
                    with sessao.post(
                        self.url, headers={"Authorization": f"Bearer {self.chave}",
                                           "Accept": "application/json"},
                        json={"peso_kg": peso}, timeout=(5, 15),
                        allow_redirects=False, stream=True,
                    ) as resposta:
                        codigo = resposta.status_code
                    sucesso = 200 <= codigo < 300
                    transitorio = codigo in TRANSITORIOS
                    if not sucesso:
                        erro = "falha HTTP"
                except requests.RequestException:
                    sucesso, transitorio = False, True
                    erro = "falha de rede ou timeout"
                LOG.info("Peso=%s kg HTTP=%s resultado=%s", peso, codigo,
                         "enviado" if sucesso else erro)
                with self.condicao:
                    if sucesso:
                        self.ultimo_enviado = peso
                        if self.pendente == peso:
                            self.pendente = None
                        atraso = 1
                        self.informar(f"AgroLima: {peso} kg enviado.")
                    elif not transitorio:
                        self.bloqueado = True
                        self.informar(f"AgroLima: HTTP {codigo}. Corrija a configuração e reinicie.")
                    else:
                        # A falha pode ter ocorrido depois da gravação no servidor.
                        self.ultimo_enviado = None
                        self.informar(f"AgroLima: envio pendente ({erro}; HTTP {codigo}).")
                        # Um peso novo substitui o pendente, mas respeita o backoff.
                        self.condicao.wait_for(lambda: self.encerrado, timeout=atraso)
                        atraso = min(atraso * 2, 60)
