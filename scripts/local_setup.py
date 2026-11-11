"""Prepare an isolated macOS PostgreSQL database without touching other projects."""
from pathlib import Path
import shutil
import subprocess
from cryptography.fernet import Fernet
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def binary(name):
    candidate = shutil.which(name)
    if candidate:
        return candidate
    for version in ('18', '17', '16', '15', '14'):
        path = Path('/opt/homebrew/opt') / ('postgresql@' + version) / 'bin' / name
        if path.exists():
            return str(path)
    raise SystemExit('Install PostgreSQL or use the Docker instructions in README.md.')


def run(*args, check=True, **kwargs):
    return subprocess.run(list(args), check=check, cwd=ROOT, **kwargs)


def main():
    env_path = ROOT / '.env'
    if env_path.exists():
        if 'MFA_ENCRYPTION_KEY=' not in env_path.read_text():
            with env_path.open('a') as file:
                file.write('\nMFA_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\n')
            env_path.chmod(0o600)
            print('Created a private authenticator encryption key. Back up .env separately from the database.')
        print('Using existing .env configuration. No database configuration changed.')
        return
    cluster = ROOT / 'var/postgres'
    cluster.parent.mkdir(exist_ok=True, mode=0o700)
    if not (cluster / 'PG_VERSION').exists():
        run(binary('initdb'), '-D', str(cluster), '--auth-local=trust', '--auth-host=scram-sha-256')
    if run(binary('pg_ctl'), '-D', str(cluster), 'status', check=False, stdout=subprocess.DEVNULL).returncode:
        # Socket access is restricted by the 0700 cluster directory. No TCP listener.
        run(binary('pg_ctl'), '-D', str(cluster), '-l', str(ROOT / 'var/postgres.log'),
            '-o', f"-k '{cluster}' -p 55432 -h ''", 'start')
    check = run(binary('psql'), '-h', str(cluster), '-p', '55432', '-d', 'postgres', '-Atc',
                "SELECT 1 FROM pg_database WHERE datname = 'lubriflow'", capture_output=True, text=True)
    if check.stdout.strip() != '1':
        run(binary('createdb'), '-h', str(cluster), '-p', '55432', 'lubriflow')
    url = 'postgresql+psycopg:///lubriflow?host=' + quote(str(cluster), safe='/') + '&port=55432'
    with env_path.open('x') as file:
        file.write('DATABASE_URL=' + url + '\nAPP_ORIGIN=http://localhost:3000\nENVIRONMENT=development\nDOCUMENT_ROOT=./var/documents\n')
        file.write('MFA_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\n')
    env_path.chmod(0o600)
    print('Local business database configured. Test records remain in the separate test database.')


if __name__ == '__main__':
    main()
