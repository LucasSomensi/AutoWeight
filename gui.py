"""Painel local; somente a thread principal acessa os widgets do Tk."""

import threading
import time
import tkinter as tk
from datetime import datetime

import cv2
import numpy as np


def formatar_peso(peso):
    return "—" if peso is None else f"{peso:,}".replace(",", ".")


def ultimo_registro(pasta):
    """Recupera a última pesagem pelo nome publicado pelo gravador."""
    if not pasta.exists():
        return None
    for caminho in sorted(pasta.glob("*.jpg"), reverse=True):
        try:
            data, peso = caminho.stem.rsplit("-", 1)
            horario = datetime.strptime(data, "%Y-%m-%d-%H-%M-%S-%f")
            return caminho, horario, int(peso.removesuffix("kg"))
        except ValueError:
            continue
    return None


class Painel:
    def __init__(self, root, app, verbose=False):
        self.root, self.app = root, app
        self.foto_atual = None
        self.frame = None
        self.imagem = None
        self.fechando = False
        root.title("AutoWeight • Sala da balança")
        root.geometry("1100x800")
        root.minsize(760, 600)
        root.configure(bg="#eef2f6")
        root.protocol("WM_DELETE_WINDOW", self.fechar)

        topo = tk.Frame(root, bg="#152b40", padx=28, pady=20)
        topo.pack(fill="x")
        self.label(topo, "AutoWeight", 24, "#ffffff", "#152b40", bold=True).pack(anchor="w")
        self.label(topo, "MONITORAMENTO DE PESAGEM", 10, "#a9c0d4", "#152b40").pack(anchor="w", pady=(4, 0))

        resumo = tk.Frame(root, bg="#eef2f6")
        resumo.pack(fill="x", padx=28, pady=20)
        peso_card = tk.Frame(resumo, bg="white", padx=24, pady=16)
        peso_card.pack(side="left", fill="both", expand=True, padx=(0, 16))
        self.label(peso_card, "PESO ATUAL DA BALANÇA", 11).pack(anchor="w")
        linha = tk.Frame(peso_card, bg="white")
        linha.pack(anchor="w")
        self.peso = self.label(linha, "—", 46, bold=True)
        self.peso.pack(side="left")
        self.label(linha, "kg", 18).pack(side="left", padx=12, pady=(20, 0))
        self.balanca = self.label(peso_card, "Aguardando leitura…", 10)
        self.balanca.pack(anchor="w")

        camera_card = tk.Frame(resumo, bg="white", padx=24, pady=16)
        camera_card.pack(side="left", fill="both")
        self.label(camera_card, "CÂMERA", 11).pack(anchor="w")
        self.camera = self.label(camera_card, "● Aguardando imagem", 15, "#9a6700", bold=True)
        self.camera.pack(anchor="w", pady=18)
        self.label(camera_card, "Estado atualizado automaticamente", 10).pack(anchor="w")

        registro = tk.Frame(root, bg="white", padx=20, pady=16)
        registro.pack(fill="both", expand=True, padx=28, pady=(0, 16))
        self.label(registro, "ÚLTIMA FOTO REGISTRADA", 11, bold=True).pack(anchor="w")
        self.detalhes = self.label(registro, "Nenhuma pesagem registrada", 17, bold=True)
        self.detalhes.pack(anchor="w", pady=(8, 4))
        self.aviso = self.label(registro, "A foto aparecerá após a gravação da pesagem.", 10)
        self.aviso.pack(anchor="w", pady=(0, 12))
        self.canvas = tk.Canvas(registro, bg="#e5ebf0", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.desenhar)
        self.status = self.label(root, "Iniciando…", 10, bg="#eef2f6")
        self.status.pack(anchor="w", padx=28, pady=(0, 16))

        try:
            anterior = ultimo_registro(app.PASTA_DADOS)
            if anterior:
                self.carregar_foto(*anterior)
        except OSError:
            self.aviso.configure(text="Não foi possível consultar os registros anteriores.")
        self.worker = threading.Thread(target=app.executar, args=(verbose,), daemon=True)
        self.worker.start()
        self.atualizar()

    @staticmethod
    def label(parent, text, size, fg="#243b50", bg="white", bold=False):
        return tk.Label(parent, text=text, bg=bg, fg=fg,
                        font=("Segoe UI", size, "bold" if bold else "normal"), anchor="w")

    def carregar_foto(self, caminho, horario, peso, branca=False):
        self.foto_atual = caminho
        self.detalhes.configure(text=f"{horario:%d/%m/%Y às %H:%M:%S}   •   {formatar_peso(peso)} kg")
        try:
            self.frame = cv2.imdecode(np.frombuffer(caminho.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            if self.frame is None:
                raise ValueError("JPEG inválido")
            branca = branca or bool(np.all(self.frame == 255))
            self.aviso.configure(
                text="Imagem branca de contingência — foto da câmera indisponível." if branca else "Foto salva com sucesso.",
                fg="#9a6700" if branca else "#287550")
        except (OSError, ValueError, cv2.error):
            self.frame = None
            self.aviso.configure(text="Não foi possível abrir a foto registrada.", fg="#b42318")
        self.desenhar()

    def desenhar(self, event=None):
        self.canvas.delete("all")
        largura, altura = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.frame is None:
            self.canvas.create_text(largura / 2, altura / 2, text="Aguardando foto da pesagem",
                                    fill="#64788b", font=("Segoe UI", 15))
            return
        h, w = self.frame.shape[:2]
        escala = min(max(largura, 1) / w, max(altura, 1) / h)
        reduzida = cv2.resize(self.frame, (max(1, int(w * escala)), max(1, int(h * escala))),
                              interpolation=cv2.INTER_AREA)
        ok, png = cv2.imencode(".png", reduzida)
        if ok:
            self.imagem = tk.PhotoImage(data=png.tobytes(), format="png")
            self.canvas.create_image(largura / 2, altura / 2, image=self.imagem)

    def atualizar(self):
        if self.fechando:
            return
        estado = self.app.obter_estado()
        recente = estado["recebido"] is not None and time.monotonic() - estado["recebido"] <= 3
        self.peso.configure(text=formatar_peso(estado["peso"] if recente else None))
        self.balanca.configure(text="Recebendo dados" if recente and estado["peso"] is not None else "Sem leitura recente da balança")
        conectada = self.app.camera is not None and self.app.camera.conectada()
        self.camera.configure(text="● Conectada" if conectada else "● Sem imagem recente",
                              fg="#287550" if conectada else "#b42318")
        if estado["foto"] is not None and estado["foto"] != self.foto_atual:
            self.carregar_foto(estado["foto"], estado["hora"], estado["peso_foto"], estado["foto_branca"])
        self.status.configure(text=estado["mensagem"])
        self.root.after(200, self.atualizar)

    def fechar(self):
        self.fechando = True
        self.app.parar.set()
        self.status.configure(text="Encerrando conexões…")
        self.aguardar_encerramento()

    def aguardar_encerramento(self):
        if self.worker.is_alive():
            self.root.after(100, self.aguardar_encerramento)
        else:
            self.root.destroy()


def iniciar(app, verbose=False):
    root = tk.Tk()
    Painel(root, app, verbose)
    root.mainloop()
