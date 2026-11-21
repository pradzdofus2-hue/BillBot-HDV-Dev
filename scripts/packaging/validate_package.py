import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from zipfile import ZipFile

import psutil


def close_window(pid: int) -> None:
    try:
        owner_process = psutil.Process(pid)
        owners = {pid, *(child.pid for child in owner_process.children(recursive=True))}
    except psutil.NoSuchProcess:
        return
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    def visit(hwnd: int, _: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in owners:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True

    user32.EnumWindows(callback_type(visit), 0)


def validate_package(folder: Path) -> None:
    version = folder / "_internal/VERSION"
    if not version.is_file():
        raise RuntimeError("Packaged VERSION file is missing")
    expected_client_id = os.environ.get("ASTRABOT_GITHUB_CLIENT_ID", "").strip()
    if expected_client_id:
        client_id = folder / "_internal/github-client-id.txt"
        if not client_id.is_file() or client_id.read_text(encoding="utf-8").strip() != expected_client_id:
            raise RuntimeError("Packaged GitHub client ID does not match ASTRABOT_GITHUB_CLIENT_ID")
    if not (folder / "_internal/UnityPy/resources/lzma.tpk").is_file():
        raise RuntimeError("Packaged UnityPy image decoder resources are missing")
    if not (folder / "_internal/fmod_toolkit/libfmod/Windows/x64/fmod.dll").is_file():
        raise RuntimeError("Packaged UnityPy FMOD dependency is missing")
    if not (folder / "_internal/archspec/json/cpu/microarchitectures.json").is_file():
        raise RuntimeError("Packaged UnityPy CPU detection data is missing")
    with ZipFile(folder / "_internal/DBDofusUnity/datas/bundles/maps.zip") as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Packaged maps.zip is corrupted")
    with tempfile.TemporaryDirectory(prefix="bot-package-") as temporary:
        root = Path(temporary)
        package = root / "release"
        shutil.copytree(folder, package)
        (package / "_internal/github-client-id.txt").unlink(missing_ok=True)
        profile = root / "profile"
        environment = dict(os.environ)
        environment.update(
            USERPROFILE=str(profile),
            APPDATA=str(profile / "AppData/Roaming"),
            LOCALAPPDATA=str(profile / "AppData/Local"),
            PYTHON_DOTENV_DISABLED="1",
            PLAYWRIGHT_BROWSERS_PATH=str(root / "absent-browser-cache"),
            THISISASTRABOT_SKIP_UPDATE_ONCE="1",
        )
        for name in (
            "OBF_GAME_DIR",
            "NON_OBF_GAME_DIR",
            "PROTOC_PATH",
            "IDA_EXE",
            "OPENAI_API_KEY",
            "SONJI_API_KEY",
            "ASTRABOT_GITHUB_CLIENT_ID",
        ):
            environment.pop(name, None)
        driver = package / "_internal/playwright/driver"
        subprocess.run(
            [
                str(driver / "node.exe"),
                str(driver / "package/cli.js"),
                "screenshot",
                "--channel=chromium",
                "about:blank",
                str(root / "browser.png"),
            ],
            cwd=root,
            env=environment | {"PLAYWRIGHT_BROWSERS_PATH": "0"},
            check=True,
            timeout=60,
        )
        log_path = profile / "AppData/Local/AstraBot/resources/diagnostics.log"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen(
            [str(package / "AstraBot.exe"), "--no-auto"],
            cwd=root,
            env=environment,
            startupinfo=startup,
        )
        try:
            deadline = time.monotonic() + 120
            log = ""
            while time.monotonic() < deadline:
                log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
                if "Application ready." in log:
                    raise RuntimeError("Packaged startup accepted an installation without Dofus")
                if "Startup task failed: The installed Dofus version is missing or unreadable." in log:
                    break
                if process.poll() is not None or "ERROR" in log:
                    raise RuntimeError(f"Packaged startup failed:\n{log}")
                time.sleep(0.2)
            else:
                raise TimeoutError(f"Packaged startup did not finish:\n{log}")
            deadline = time.monotonic() + 30
            while process.poll() is None:
                close_window(process.pid)
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Packaged application did not close:\n{log}") from None
            if process.returncode != 1:
                raise RuntimeError(f"Missing Dofus must produce exit code 1, got {process.returncode}")
            print("PASS: bundled Chromium, VERSION file, missing Dofus detected and exit code 1")
        finally:
            if process.poll() is None:
                try:
                    children = psutil.Process(process.pid).children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
                for child in children:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                process.kill()
                process.wait()


if __name__ == "__main__":
    validate_package(Path(sys.argv[1]).resolve())
