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
import subprocess  # nosec B404 - only used for hardcoded venv/uv invocations, never user input
import sys

_raw_cache_dir = os.environ.get("TERRASCOPE_CACHE_DIR")
if _raw_cache_dir is None:
    CACHE_DIR = os.path.expanduser("~/.qgis_terrascope")
else:
    CACHE_DIR = os.path.expanduser(os.path.expandvars(_raw_cache_dir))
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
    """Create the virtual environment using uv (preferred) or stdlib venv.

    When uv is available, uses ``uv venv`` which is faster and does not
    require pip inside the venv.  Falls back to ``python -m venv`` when
    uv is not available.

    Args:
        progress_callback: Optional callable(str) for status messages.

    Returns:
        Tuple of (success, message).
    """
    from .uv_manager import uv_exists, get_uv_path

    if progress_callback:
        progress_callback("Creating virtual environment...")

    os.makedirs(CACHE_DIR, exist_ok=True)

    python_exe = None
    python_lookup_error = ""
    try:
        python_exe = _find_python_executable()
    except RuntimeError as exc:
        python_lookup_error = str(exc)
    env = _get_clean_env()
    use_uv = uv_exists()

    try:
        if use_uv:
            uv_path = get_uv_path()
            uv_python = python_exe or f"{sys.version_info.major}.{sys.version_info.minor}"
            cmd = [uv_path, "venv"]
            if python_exe is None:
                cmd.append("--managed-python")
            cmd += ["--python", uv_python, VENV_DIR]
        else:
            if python_exe is None:
                return False, python_lookup_error
            cmd = [python_exe, "-m", "venv", VENV_DIR]

        result = subprocess.run(  # nosec B603 - hardcoded `uv venv` or `python -m venv`, shell=False
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            **_subprocess_kwargs(),
        )
        if result.returncode != 0:
            if use_uv and python_exe:
                # uv venv failed; fall back to stdlib venv
                if progress_callback:
                    progress_callback(
                        "uv venv failed, falling back to python -m venv..."
                    )
                from .uv_manager import remove_uv

                remove_uv()
                use_uv = False
                cmd = [python_exe, "-m", "venv", VENV_DIR]
                result = subprocess.run(  # nosec B603 - hardcoded `python -m venv`, shell=False
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                    **_subprocess_kwargs(),
                )
                if result.returncode != 0:
                    return False, f"Failed to create venv: {result.stderr.strip()}"
            else:
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

    # When using stdlib venv, upgrade pip
    if not use_uv:
        if progress_callback:
            progress_callback("Upgrading pip...")

        try:
            subprocess.run(  # nosec B603 - hardcoded `pip install --upgrade pip` against the venv's own python
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
                **_subprocess_kwargs(),
            )
        except Exception:
            pass  # nosec B110 - pip upgrade failure is non-fatal; venv works without latest pip

    return True, "Virtual environment created successfully"


def install_packages(packages, progress_callback=None, cancel_check=None):
    """Install packages into the virtual environment.

    Uses uv when available for significantly faster installation,
    falling back to pip otherwise.

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

    from .uv_manager import uv_exists, get_uv_path

    use_uv = uv_exists()
    uv_path = get_uv_path() if use_uv else None

    for i, package in enumerate(packages, 1):
        if cancel_check and cancel_check():
            return False, "Installation cancelled by user"

        installer = "uv" if use_uv else "pip"
        if progress_callback:
            progress_callback(
                f"Installing {package} ({installer})... ({i}/{len(packages)})"
            )

        if use_uv:
            success, error = _install_single_package_uv(uv_path, python, package, env)
        else:
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
            result = subprocess.run(  # nosec B603 - hardcoded `pip install <pkg>` via venv python, shell=False
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                **_subprocess_kwargs(),
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
                    ssl_result = subprocess.run(  # nosec B603 - same pip command with --trusted-host retry, hardcoded args
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env=env,
                        **_subprocess_kwargs(),
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


def _install_single_package_uv(uv_path, python, package, env):
    """Install a single package using uv with retry logic.

    Args:
        uv_path: Path to the uv binary.
        python: Path to the venv Python executable.
        package: Pip package name to install.
        env: Clean environment dict for subprocess.

    Returns:
        Tuple of (success, error_message).
    """
    max_retries = 2
    base_cmd = [uv_path, "pip", "install", "--python", python]

    for attempt in range(max_retries + 1):
        cmd = list(base_cmd) + [package]

        try:
            result = subprocess.run(  # nosec B603 - hardcoded `uv pip install <pkg>`, shell=False
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                **_subprocess_kwargs(),
            )
            if result.returncode == 0:
                return True, ""

            stderr = result.stderr or ""
            if attempt < max_retries and _is_retryable(stderr):
                # Try with insecure hosts for SSL errors
                if _is_ssl_error(stderr):
                    ssl_cmd = list(base_cmd) + [
                        "--allow-insecure-host",
                        "pypi.org",
                        "--allow-insecure-host",
                        "files.pythonhosted.org",
                        package,
                    ]
                    ssl_result = subprocess.run(  # nosec B603 - same uv pip command with --allow-insecure-host retry, hardcoded args
                        ssl_cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env=env,
                        **_subprocess_kwargs(),
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


def _subprocess_kwargs():
    """Get platform-specific kwargs for subprocess calls.

    On Windows, suppresses the console window that would otherwise pop up
    for each subprocess invocation.

    Returns:
        Dict of keyword arguments to pass to subprocess.run().
    """
    if platform.system() == "Windows":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _is_python_executable_name(path):
    """Return True when a path name looks like a Python interpreter."""
    name = os.path.basename(path).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name in ("python", "python3"):
        return True
    if not name.startswith("python"):
        return False
    suffix = name[6:]
    if "-" in suffix:
        return False
    return suffix.isdigit() or (
        suffix.count(".") == 1 and all(part.isdigit() for part in suffix.split("."))
    )


def _is_macos_qgis_app_bundle_python(path):
    """Return True for Python binaries inside a QGIS macOS .app bundle."""
    if not (platform.system() == "Darwin" or sys.platform == "darwin"):
        return False
    parts = os.path.abspath(path).split(os.sep)
    for idx, part in enumerate(parts):
        lower = part.lower()
        if not (lower.startswith("qgis") and lower.endswith(".app")):
            continue
        return idx + 1 < len(parts) and parts[idx + 1] == "Contents"
    return False


def _python_candidate_matches_runtime(path):
    """Return True when a candidate is executable and matches QGIS Python."""
    if not path or not os.path.isfile(path) or not _is_python_executable_name(path):
        return False

    if _is_macos_qgis_app_bundle_python(path):
        return False
    try:
        result = subprocess.run(  # nosec B603
            [
                path,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=_get_clean_env(),
            **_subprocess_kwargs(),
        )
    except Exception:
        return False
    runtime_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return result.returncode == 0 and result.stdout.strip() == runtime_version


def _contents_dir_from_path(path):
    """Return the containing macOS app Contents directory for a path."""
    if not path:
        return None
    current = path if os.path.isdir(path) else os.path.dirname(path)
    for _ in range(8):
        if os.path.basename(current) == "Contents":
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _candidate_python_paths():
    """Return possible Python interpreter paths for QGIS-bundled Python."""
    candidates = []
    exe_dir = os.path.dirname(sys.executable)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    names = (f"python{py_ver}", f"python{sys.version_info.major}", "python3", "python")

    for attr in ("_base_executable", "executable"):
        value = getattr(sys, attr, None)
        if value:
            candidates.append(value)

    for attr in ("_base_prefix", "base_prefix", "prefix", "exec_prefix"):
        prefix = getattr(sys, attr, None)
        if not prefix:
            continue
        candidates.extend([os.path.join(prefix, "python.exe")])
        candidates.extend(os.path.join(prefix, "bin", name) for name in names)
        candidates.extend(
            [
                os.path.join(prefix, "Versions", py_ver, "bin", "python3"),
                os.path.join(prefix, "Versions", "Current", "bin", "python3"),
            ]
        )

    candidates.extend(os.path.join(exe_dir, name) for name in names)
    candidates.extend(
        [os.path.join(exe_dir, "python.exe"), os.path.join(exe_dir, "python3.exe")]
    )

    apps_dir = os.path.join(os.path.dirname(exe_dir), "apps")
    if os.path.isdir(apps_dir):
        for entry in sorted(os.listdir(apps_dir), reverse=True):
            if entry.lower().startswith("python"):
                candidates.append(os.path.join(apps_dir, entry, "python.exe"))

    for root in [sys.executable, getattr(sys, "_base_executable", None), sys.prefix]:
        contents_dir = _contents_dir_from_path(root)
        if not contents_dir:
            continue
        candidates.extend(os.path.join(contents_dir, "MacOS", name) for name in names)
        candidates.extend(
            os.path.join(contents_dir, "MacOS", "bin", name) for name in names
        )
        candidates.extend(
            [
                os.path.join(
                    contents_dir,
                    "Frameworks",
                    "Python.framework",
                    "Versions",
                    py_ver,
                    "bin",
                    "python3",
                ),
                os.path.join(
                    contents_dir,
                    "Frameworks",
                    "Python.framework",
                    "Versions",
                    "Current",
                    "bin",
                    "python3",
                ),
                os.path.join(contents_dir, "Resources", "python", "bin", "python3"),
                os.path.join(
                    contents_dir,
                    "Resources",
                    "Python.app",
                    "Contents",
                    "MacOS",
                    "Python",
                ),
            ]
        )

    unique = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _find_python_executable():
    """Find a real Python executable for venv creation."""
    candidates = _candidate_python_paths()
    for candidate in candidates:
        if _python_candidate_matches_runtime(candidate):
            return candidate

    candidates_text = "\n".join(f"  - {path}" for path in candidates)
    raise RuntimeError(
        "Could not find a Python executable matching the QGIS Python runtime.\n"
        f"QGIS sys.executable: {sys.executable}\n"
        f"Python version: {sys.version_info.major}.{sys.version_info.minor}\n"
        "Checked candidates:\n"
        f"{candidates_text or '  - none'}"
    )
