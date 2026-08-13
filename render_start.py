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
        # Render inicia directamente desde este archivo; recopilar aquí garantiza
        # que los estilos de aplicaciones nuevas existan en el manifiesto de WhiteNoise.
        run([sys.executable, "manage.py", "collectstatic", "--noinput", "--verbosity", "1"])
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
        "--timeout",
        os.environ.get("WEB_TIMEOUT", "120"),
        "--graceful-timeout",
        os.environ.get("WEB_GRACEFUL_TIMEOUT", "30"),
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
        "--log-level",
        os.environ.get("WEB_LOG_LEVEL", "info"),
    ])


if __name__ == "__main__":
    main()
