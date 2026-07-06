"""Clone ForgeRSS into external/ForgeRSS and prepare its Python environment."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT_DIR / "external" / "ForgeRSS"
REPO_URL = "https://github.com/tmwgsicp/ForgeRSS.git"


def main() -> None:
    if (SERVICE_DIR / ".git").exists():
        print(f"ForgeRSS already exists at {SERVICE_DIR}")
    else:
        if any(SERVICE_DIR.iterdir()):
            print(f"{SERVICE_DIR} is not empty. Clone ForgeRSS there manually if needed.")
        else:
            subprocess.run(["git", "clone", REPO_URL, str(SERVICE_DIR)], check=True)

    venv_python = _venv_python(SERVICE_DIR / ".venv")
    if not venv_python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(SERVICE_DIR / ".venv")], check=True)

    requirements = SERVICE_DIR / "requirements.txt"
    if requirements.exists():
        subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)], check=True)

    env_file = SERVICE_DIR / ".env"
    env_example = SERVICE_DIR / ".env.example"
    if env_example.exists() and not env_file.exists():
        shutil.copyfile(env_example, env_file)

    print("ForgeRSS is ready.")
    print(f"Next: cd {SERVICE_DIR} && {venv_python} -m generators.social.xiaohongshu.scraper --login")


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


if __name__ == "__main__":
    main()
