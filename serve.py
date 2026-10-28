"""Servidor para la demo y para uso real, compatible con Windows (waitress).

    python serve.py                 escucha en http://127.0.0.1:5000
    python serve.py --puerto 8000   otro puerto
    python serve.py --publico       escucha en todas las interfaces (red local o túnel)
"""

import argparse
import os

from waitress import serve

from app import create_app


def main():
    parser = argparse.ArgumentParser(description="Servidor de la plataforma de atención automatizada")
    parser.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 5000)))
    parser.add_argument("--publico", action="store_true", help="Escuchar en 0.0.0.0 en lugar de 127.0.0.1")
    args = parser.parse_args()
    host = "0.0.0.0" if args.publico else "127.0.0.1"
    app = create_app()
    print(f"Plataforma disponible en http://{'localhost' if host == '127.0.0.1' else host}:{args.puerto}")
    serve(app, host=host, port=args.puerto, threads=8)


if __name__ == "__main__":
    main()
