"""
Virtual Environment Manager for Terrascope Plugin

Manages an isolated virtual environment for plugin dependencies, keeping them
separate from QGIS's built-in Python environment.

The default location is ~/.qgis_terrascope/venv/. Override by setting the
TERRASCOPE_CACHE_DIR environment variable.
"""

import importlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys

CACHE_DIR = os.environ.get(
    "TERRASCOPE_CACHE_DIR", os.path.expanduser("~/.qgis_terrascope")
)
VENV_DIR = os.path.join(CACHE_DIR, "venv")

REQUIRED_PACKAGES = [
    ("requests", "requests"),
    ("pystac_client", "pystac-client"),
]
OPTIONAL_PACKAGES = [
    ("matplotlib", "matplotlib"),
]


def get_venv_python():
    """Get the path to the venv's Python executable.

    Returns:
        Path to the Python executable inside the venv.
    """
    if platform.system() == "Windows":
        primary = os.path.join(VENV_DIR, "Scripts", "python.exe")
        if os.path.isfile(primary):
            return primary
        fallback = os.path.join(VENV_DIR, "Scripts", "python3.exe")
        if os.path.isfile(fallback):
            return fallback
        return primary  # Return expected path even if missing (for error messages)
    path = os.path.join(VENV_DIR, "bin", "python3")
    if os.path.isfile(path):
        return path
    return os.path.join(VENV_DIR, "bin", "python")


def get_venv_site_packages():
    """Get the path to the venv's site-packages directory.

    Returns:
        Path to site-packages, or None if not found.
    """
    if platform.system() == "Windows":
        sp = os.path.join(VENV_DIR, "Lib", "site-packages")
        return sp if os.path.isdir(sp) else None

    lib_dir = os.path.join(VENV_DIR, "lib")
    if not os.path.isdir(lib_dir):
        return None
    for entry in sorted(os.listdir(lib_dir), reverse=True):
        if entry.startswith("python"):
            sp = os.path.join(lib_dir, entry, "site-packages")
            if os.path.isdir(sp):
                return sp
    return None


def venv_exists():
    """Check whether the virtual environment exists.

    Returns:
        True if the venv Python executable exists.
    """
    return os.path.isfile(get_venv_python())


def check_packages(site_packages=None):
    """Check which packages are installed in the venv.

    Args:
        site_packages: Path to site-packages directory. If None, auto-detected.

    Returns:
        Tuple of (missing_required, missing_optional) pip name lists.
    """
    if site_packages is None:
        site_packages = get_venv_site_packages()

    added = False
    if site_packages and site_packages not in sys.path:
        sys.path.insert(0, site_packages)
        added = True

    try:
        importlib.invalidate_caches()
        missing_required = []
        for import_name, pip_name in REQUIRED_PACKAGES:
            if importlib.util.find_spec(import_name) is None:
                missing_required.append(pip_name)

        missing_optional = []
        for import_name, pip_name in OPTIONAL_PACKAGES:
            if importlib.util.find_spec(import_name) is None:
                missing_optional.append(pip_name)

        return missing_required, missing_optional
    finally:
        if added and site_packages in sys.path:
            sys.path.remove(site_packages)


def get_venv_status():
    """Get the current status of the virtual environment and its packages.

    Returns:
        Tuple of (is_ready, message, missing_required, missing_optional).
    """
    if not venv_exists():
        all_req = [p for _, p in REQUIRED_PACKAGES]
        all_opt = [p for _, p in OPTIONAL_PACKAGES]
        return False, "Virtual environment not found", all_req, all_opt

    site_packages = get_venv_site_packages()
    if site_packages is None:
        all_req = [p for _, p in REQUIRED_PACKAGES]
        all_opt = [p for _, p in OPTIONAL_PACKAGES]
        return False, "site-packages directory not found in venv", all_req, all_opt

    missing_req, missing_opt = check_packages(site_packages)
    if missing_req:
        return (
            False,
            f"Missing required packages: {', '.join(missing_req)}",
            missing_req,
            missing_opt,
        )

    return True, "All required packages installed", [], missing_opt


def ensure_venv_packages():
    """Add the venv's site-packages to sys.path so packages are importable.

    This is idempotent and safe to call multiple times.

    Returns:
        True if site-packages is on sys.path, False if venv doesn't exist.
    """
    site_packages = get_venv_site_packages()
    if site_packages is None:
        return False

    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
        importlib.invalidate_caches()

    return True


def create_venv(progress_callback=None):
    """Create the virtual environment.

    Args:
        progress_callback: Optional callable(str) for status messages.

    Returns:
        Tuple of (success, message).
    """
    if progress_callback:
        progress_callback("Creating virtual environment...")

    os.makedirs(CACHE_DIR, exist_ok=True)

    python_exe = _find_python_executable()
    env = _get_clean_env()
    try:
        result = subprocess.run(
            [python_exe, "-m", "venv", VENV_DIR],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode != 0:
            return False, f"Failed to create venv: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Timed out creating virtual environment"
    except Exception as e:
        return False, f"Error creating virtual environment: {e}"

    if not venv_exists():
        return (
            False,
            "Virtual environment was created but Python executable not found. "
            f"Python used: {python_exe}",
        )

    # Upgrade pip in the venv
    if progress_callback:
        progress_callback("Upgrading pip...")

    try:
        subprocess.run(
            [
                get_venv_python(),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "--disable-pip-version-check",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except Exception:
        pass  # pip upgrade failure is non-fatal

    return True, "Virtual environment created successfully"


def install_packages(packages, progress_callback=None, cancel_check=None):
    """Install packages into the virtual environment.

    Args:
        packages: List of pip package names to install.
        progress_callback: Optional callable(str) for status messages.
        cancel_check: Optional callable() that returns True if cancelled.

    Returns:
        Tuple of (success, message).
    """
    if not packages:
        return True, "No packages to install"

    if not venv_exists():
        return False, "Virtual environment does not exist"

    env = _get_clean_env()
    python = get_venv_python()
    failed = []

    for i, package in enumerate(packages, 1):
        if cancel_check and cancel_check():
            return False, "Installation cancelled by user"

        if progress_callback:
            progress_callback(f"Installing {package}... ({i}/{len(packages)})")

        success, error = _install_single_package(python, package, env)
        if not success:
            failed.append((package, error))

    if failed:
        details = "; ".join(f"{pkg}: {err}" for pkg, err in failed)
        return False, f"Failed to install: {details}"

    return True, "All packages installed successfully"


def remove_venv():
    """Remove the virtual environment directory.

    Returns:
        True on success, False on failure.
    """
    if not os.path.exists(VENV_DIR):
        return True
    try:
        shutil.rmtree(VENV_DIR)
        return True
    except Exception:
        return False


def _install_single_package(python, package, env):
    """Install a single package with retry logic.

    Args:
        python: Path to the venv Python executable.
        package: Pip package name to install.
        env: Clean environment dict for subprocess.

    Returns:
        Tuple of (success, error_message).
    """
    max_retries = 2
    base_cmd = [
        python,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]

    for attempt in range(max_retries + 1):
        cmd = list(base_cmd)
        if attempt > 0:
            cmd.append("--no-cache-dir")
        cmd.append(package)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            if result.returncode == 0:
                return True, ""

            stderr = result.stderr or ""
            if attempt < max_retries and _is_retryable(stderr):
                # Try with trusted hosts for SSL errors
                if _is_ssl_error(stderr):
                    cmd = list(base_cmd) + [
                        "--trusted-host",
                        "pypi.org",
                        "--trusted-host",
                        "files.pythonhosted.org",
                        "--no-cache-dir",
                        package,
                    ]
                    ssl_result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env=env,
                    )
                    if ssl_result.returncode == 0:
                        return True, ""
                continue

            return False, _classify_error(stderr, package)

        except subprocess.TimeoutExpired:
            if attempt < max_retries:
                continue
            return False, f"Installation of {package} timed out"
        except Exception as e:
            return False, str(e)

    return False, f"Failed to install {package} after {max_retries + 1} attempts"


def _is_retryable(stderr):
    """Check if a pip error is worth retrying.

    Args:
        stderr: Standard error output from pip.

    Returns:
        True if the error is likely transient.
    """
    retryable_patterns = [
        "SSL",
        "CERTIFICATE_VERIFY_FAILED",
        "ConnectionError",
        "ConnectionReset",
        "THESE PACKAGES DO NOT MATCH THE HASHES",
        "ReadTimeoutError",
        "ConnectTimeoutError",
    ]
    return any(p in stderr for p in retryable_patterns)


def _is_ssl_error(stderr):
    """Check if a pip error is SSL-related.

    Args:
        stderr: Standard error output from pip.

    Returns:
        True if the error is SSL-related.
    """
    return "SSL" in stderr or "CERTIFICATE" in stderr


def _classify_error(stderr, package):
    """Classify a pip error into a user-friendly message.

    Args:
        stderr: Standard error output from pip.
        package: Package name that failed.

    Returns:
        User-friendly error message.
    """
    if "Permission denied" in stderr or "Access is denied" in stderr:
        return (
            f"Permission denied installing {package}. "
            "Try running QGIS as administrator."
        )
    if "SSL" in stderr or "CERTIFICATE" in stderr:
        return (
            f"SSL error installing {package}. "
            "Check your internet connection and firewall settings."
        )
    if "No matching distribution" in stderr:
        return (
            f"Package {package} not found for your Python version. "
            "Check the package name and Python compatibility."
        )
    if "No module named pip" in stderr:
        return (
            "pip is not available in the virtual environment. "
            f"Try removing {VENV_DIR} and reinstalling."
        )
    # Return last few relevant lines of stderr
    lines = stderr.strip().split("\n")
    relevant = [ln for ln in lines if ln.strip() and not ln.startswith("WARNING")]
    return (
        "\n".join(relevant[-3:]) if relevant else f"Unknown error installing {package}"
    )


def _get_clean_env():
    """Get a clean environment for subprocess calls.

    Removes QGIS-specific Python variables that could interfere with
    venv creation and pip installs.

    Returns:
        Environment dict safe for subprocess use.
    """
    env = os.environ.copy()
    for var in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(var, None)
    return env


def _find_python_executable():
    """Find a working Python executable for venv creation.

    On QGIS Windows, sys.executable may point to qgis-bin.exe rather than
    a Python interpreter. This function searches for the actual Python
    executable using multiple strategies.

    Returns:
        Path to a Python executable, or sys.executable as fallback.
    """
    if platform.system() != "Windows":
        return sys.executable

    # Strategy 1: Check if sys.executable is already Python
    exe_name = os.path.basename(sys.executable).lower()
    if exe_name in ("python.exe", "python3.exe"):
        return sys.executable

    # Strategy 2: Use sys._base_prefix to find the Python installation.
    # On QGIS Windows, sys._base_prefix typically points to
    # C:\Program Files\QGIS 3.x\apps\Python3x\
    base_prefix = getattr(sys, "_base_prefix", None) or sys.prefix
    python_in_prefix = os.path.join(base_prefix, "python.exe")
    if os.path.isfile(python_in_prefix):
        return python_in_prefix

    # Strategy 3: Look for python.exe next to sys.executable
    exe_dir = os.path.dirname(sys.executable)
    for name in ("python.exe", "python3.exe"):
        candidate = os.path.join(exe_dir, name)
        if os.path.isfile(candidate):
            return candidate

    # Strategy 4: Walk up from sys.executable to find apps/Python3x/python.exe
    # Typical QGIS layout: .../QGIS 3.x/bin/qgis-bin.exe
    #                       .../QGIS 3.x/apps/Python3x/python.exe
    parent = os.path.dirname(exe_dir)
    apps_dir = os.path.join(parent, "apps")
    if os.path.isdir(apps_dir):
        for entry in sorted(os.listdir(apps_dir), reverse=True):
            if entry.lower().startswith("python"):
                candidate = os.path.join(apps_dir, entry, "python.exe")
                if os.path.isfile(candidate):
                    return candidate

    # Strategy 5: Use shutil.which as last resort
    which_python = shutil.which("python")
    if which_python:
        return which_python

    # Fallback: return sys.executable (may fail, but preserves current behavior)
    return sys.executable
