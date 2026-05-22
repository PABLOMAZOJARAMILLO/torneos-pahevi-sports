import os
import subprocess
import sys
import traceback


def run(command):
    print(f"==> Ejecutando: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def main():
    try:
        print("==> Iniciando Torneos Pahevi Sports", flush=True)
        print(f"==> DATABASE_URL configurada: {'si' if os.environ.get('DATABASE_URL') else 'no'}", flush=True)
        run([sys.executable, "manage.py", "showmigrations", "torneos"])
        run([sys.executable, "manage.py", "migrate", "--noinput", "--verbosity", "2"])
    except Exception:
        print("==> ERROR APLICANDO MIGRACIONES", flush=True)
        traceback.print_exc()
        raise

    port = os.environ.get("PORT", "10000")
    run([
        "gunicorn",
        "torneos_pahevi_sports.wsgi",
        "--bind",
        f"0.0.0.0:{port}",
    ])


if __name__ == "__main__":
    main()
