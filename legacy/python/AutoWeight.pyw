"""Abre o painel pelo Python para Windows, sem console."""

import os
import sys


def iniciar():
    # pythonw não fornece os fluxos do console; mantém prints compatíveis.
    with open(os.devnull, "w", encoding="utf-8") as saida:
        stdout, stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = saida
            sys.stderr = saida
            import main
            from gui import iniciar as abrir_painel

            abrir_painel(main)
        except Exception as erro:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            try:
                messagebox.showerror(
                    "AutoWeight — erro ao iniciar",
                    f"Não foi possível abrir o programa.\n\n{type(erro).__name__}: {erro}",
                    parent=root,
                )
            finally:
                root.destroy()
        finally:
            sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    iniciar()
