"""Corre localmente las mismas verificaciones que la integración continua (.github/workflows/ci.yml).

Uso:
    python scripts/verificar.py                      análisis estático y pruebas con el Python actual
    python scripts/verificar.py --versiones 3.10 3.11 3.12 3.13
                                                     pruebas en varias versiones (requiere uv)
    python scripts/verificar.py --auditoria          agrega pip-audit sobre requirements.txt y requirements-e2e.txt
    python scripts/verificar.py --e2e                agrega las pruebas con navegador y de accesibilidad
                                                     (requieren requirements-e2e.txt y Chromium)

Devuelve código de salida distinto de cero si alguna verificación falla e imprime un resumen
listo para pegar en el pull request.
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COBERTURA_MINIMA = 85


def correr(nombre: str, comando: list[str], **kwargs) -> tuple[str, bool, str, float]:
    inicio = time.time()
    resultado = subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True, **kwargs)
    salida = (resultado.stdout + resultado.stderr).strip()
    return nombre, resultado.returncode == 0, salida, time.time() - inicio


def resumen_pytest(salida: str) -> str:
    pruebas = re.findall(r"(\d+) passed", salida)
    fallas = re.findall(r"(\d+) failed", salida)
    esperadas = re.findall(r"(\d+) xfailed", salida)
    cobertura = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+%)", salida)
    partes = []
    if pruebas:
        partes.append(f"{pruebas[-1]} pruebas")
    if fallas:
        partes.append(f"{fallas[-1]} fallidas")
    if esperadas:
        partes.append(f"{esperadas[-1]} fallas esperadas de issues pendientes")
    if cobertura:
        partes.append(f"cobertura {cobertura.group(1)}")
    return ", ".join(partes) or salida.splitlines()[-1] if salida else ""


def pruebas_en_version(version: str) -> tuple[str, bool, str, float]:
    uv = shutil.which("uv")
    if not uv:
        return f"Pruebas Python {version}", False, "uv no está instalado", 0.0
    carpeta = Path(tempfile.mkdtemp(prefix=f"ci-{version}-"))
    entorno = carpeta / "venv"
    pasos = [
        [uv, "venv", "-q", "-p", version, str(entorno)],
        [uv, "pip", "install", "-q", "-p", str(entorno), "-r", "requirements-dev.txt"],
    ]
    for paso in pasos:
        nombre, ok, salida, _ = correr(f"Pruebas Python {version}", paso)
        if not ok:
            return nombre, False, salida, 0.0
    python = entorno / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    nombre, ok, salida, duracion = correr(
        f"Pruebas Python {version}",
        [str(python), "-m", "pytest", "--cov=app", "--cov-report=term", f"--cov-fail-under={COBERTURA_MINIMA}"],
    )
    shutil.rmtree(carpeta, ignore_errors=True)
    return nombre, ok, salida, duracion


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versiones", nargs="*", help="Versiones de Python para la matriz de pruebas (usa uv)")
    parser.add_argument("--auditoria", action="store_true", help="Auditar dependencias con pip-audit")
    parser.add_argument("--e2e", action="store_true", help="Pruebas con navegador y auditoría de accesibilidad")
    args = parser.parse_args()

    resultados = [
        correr("Análisis estático (ruff check)", [sys.executable, "-m", "ruff", "check", "."]),
        correr("Formato (ruff format --check)", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ]
    if args.versiones:
        resultados += [pruebas_en_version(v) for v in args.versiones]
    else:
        resultados.append(
            correr(
                f"Pruebas Python {platform.python_version()}",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--cov=app",
                    "--cov-report=term",
                    f"--cov-fail-under={COBERTURA_MINIMA}",
                ],
            )
        )
    if args.e2e:
        resultados.append(
            correr(
                "Pruebas con navegador y accesibilidad (Playwright, axe)",
                [sys.executable, "-m", "pytest", "tests/e2e", "-m", "e2e", "-p", "no:cacheprovider"],
            )
        )
    if args.auditoria:
        for archivo in ("requirements.txt", "requirements-e2e.txt"):
            resultados.append(
                correr(
                    f"Auditoría de dependencias (pip-audit, {archivo})",
                    [sys.executable, "-m", "pip_audit", "-r", archivo, "--progress-spinner", "off"],
                )
            )

    print("\n### Verificación local\n")
    print("| Verificación | Resultado | Detalle |")
    print("|---|---|---|")
    todo_ok = True
    for nombre, ok, salida, duracion in resultados:
        todo_ok &= ok
        if nombre.startswith("Pruebas"):
            detalle = resumen_pytest(salida)
        elif "pip-audit" in nombre:
            detalle = "sin vulnerabilidades conocidas" if ok else salida.splitlines()[-1]
        else:
            detalle = salida.splitlines()[-1] if salida else ""
        print(f"| {nombre} | {'correcto' if ok else 'FALLA'} | {detalle} ({duracion:.0f} s) |")
    if not todo_ok:
        for nombre, ok, salida, _ in resultados:
            if not ok:
                print(f"\n--- {nombre} ---\n{salida[-3000:]}")
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
