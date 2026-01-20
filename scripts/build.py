#!/usr/bin/env python3
"""Build script for creating KuLo standalone binaries.

This script uses PyInstaller to create a single self-contained executable.
It supports two modes:
1. Docker Build (Default): Builds inside a container for max compatibility (glibc 2.31 / RHEL9).
2. Local Build (--local): Builds directly on the host machine.

Usage:
    # Build for broad Linux compatibility (uses Docker)
    python scripts/build.py

    # Build locally (for development or non-Linux platforms)
    python scripts/build.py --local

    # Debug variants
    python scripts/build.py --debug
    python scripts/build.py --local --debug
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import re
from pathlib import Path


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

# Embedded Dockerfile for hermetic builds
# Uses Debian Bullseye (glibc 2.31) for compatibility with RHEL 9 (glibc 2.34)
DOCKERFILE_CONTENT = r"""
FROM python:3.12-slim-bullseye

# Install build dependencies
# binutils is needed for PyInstaller to analyze binaries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Ensure output directories exist and have broad permissions
RUN mkdir -p dist build && chmod 777 dist build

# Copy project files for dependency installation
COPY pyproject.toml uv.lock LICENSE README.md ./
# Install dependencies into system environment
RUN uv pip install --system --no-cache .[dev]

# The rest of the source will be mounted at runtime
"""


def get_version() -> str:
    """Get the project version from pyproject.toml.

    Returns:
        Version string (e.g., '2.1.0').
    """
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return "unknown"

    with open(pyproject_path, "r") as f:
        content = f.read()
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if match:
            return match.group(1)
    return "unknown"


def get_default_binary_name() -> str:
    """Get the default binary name based on project version.

    Returns:
        Binary name string (e.g., 'kulo-v2.1.0').
    """
    version = get_version()
    return f"kulo-v{version}"


def clean_build_artifacts() -> None:
    """Remove previous build artifacts."""
    for directory in [BUILD_DIR, DIST_DIR]:
        if directory.exists():
            print(f"Cleaning {directory}...")
            try:
                shutil.rmtree(directory)
            except PermissionError:
                print(f"Warning: Could not clean {directory} due to permissions. Skipping.")


def check_docker() -> bool:
    """Check if Docker is available."""
    try:
        subprocess.run(
            ["podman", "--version"], 
            check=True, 
            capture_output=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def build_locally(
    binary_name: str,
    debug: bool = False,
    clean: bool = True,
    verify: bool = True,
) -> int:
    """Run PyInstaller locally to create the executable.

    Args:
        binary_name: Name for the output binary.
        debug: Whether to build in debug mode.
        clean: Whether to clean artifacts before building.
        verify: Whether to verify the binary after building.

    Returns:
        Exit code (0 for success).
    """
    print(f"building locally: {binary_name}")

    if clean:
        clean_build_artifacts()

    # PyInstaller arguments
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", binary_name,
        "--clean",
        "--noconfirm",
        "--onefile",
        "--specpath", "/tmp", # Write spec file to tmp to avoid permission issues
        "--distpath", str(DIST_DIR),
        "--workpath", "/tmp/build", # Build in tmp to avoid permission issues
    ]

    if not debug:
        # Strip debug info and optimize
        args.extend([
            "--strip",
            "--log-level", "WARN",
        ])
    else:
        args.extend([
            "--log-level", "DEBUG",
        ])

    # Hidden imports that PyInstaller might miss
    hidden_imports = [
        "kubernetes_asyncio",
        "kubernetes_asyncio.client",
        "kubernetes_asyncio.config",
        "kubernetes_asyncio.watch",
        "rich",
        "rich.console",
        "rich.table",
        "rich.text",
        "rich.panel",
    ]

    for module in hidden_imports:
        args.extend(["--hidden-import", module])

    # Exclude unnecessary modules to reduce size
    excludes = [
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL",
        "scipy",
        "pandas",
        "setuptools",
        "wheel",
    ]

    for module in excludes:
        args.extend(["--exclude-module", module])

    # Entry point
    args.append(str(SRC_DIR / "kulo" / "main.py"))

    print(f"Command: {' '.join(args)}")

    env = os.environ.copy()
    # Force PyInstaller to use /tmp for caching to avoid writing to read-only/no-perm home or project dir
    env["PYINSTALLER_CONFIG_DIR"] = "/tmp/pyinstaller_config"
    env["XDG_CACHE_HOME"] = "/tmp/.cache"

    try:
        subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=not debug,
            text=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        print(f"Build failed with exit code {e.returncode}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return 1

    binary_path = DIST_DIR / binary_name
    
    # Simple verification
    if verify and binary_path.exists():
        print(f"Verifying {binary_path}...")
        try:
            subprocess.run([str(binary_path), "--version"], check=True, capture_output=True)
            print("Verification successful.")
        except Exception as e:
            print(f"Verification failed: {e}")
            return 1

    # Print summary
    if binary_path.exists():
        size_mb = binary_path.stat().st_size / (1024 * 1024)
        print(f"\nSUCCESS: {binary_path} ({size_mb:.2f} MB)")
        return 0
    
    return 1


def build_in_docker(binary_name: str, debug: bool = False) -> int:
    """Orchestrate the build inside a Docker container.

    Args:
        binary_name: Name for the output binary.
        debug: Whether to enable debug output.

    Returns:
        Exit code (0 for success).
    """
    if not check_docker():
        print("Error: Docker not found. Install Docker or use --local to build on host.")
        return 1

    image_name = "kulo-builder"
    print(f"Building Docker image: {image_name}...")

    with tempfile.TemporaryDirectory() as temp_dir:
        dockerfile_path = Path(temp_dir) / "Dockerfile"
        with open(dockerfile_path, "w") as f:
            f.write(DOCKERFILE_CONTENT.strip())

        # Build image
        cmd_build = [
            "podman", "build",
            "-t", image_name,
            "-f", str(dockerfile_path),
            str(PROJECT_ROOT)  # Context is project root to copy pyproject.toml etc
        ]
        
        try:
            subprocess.run(cmd_build, check=True)
        except subprocess.CalledProcessError:
            print("Failed to build Docker image.")
            return 1

    print("\nRunning build inside container...")
    
    # Make sure dist exists so we can map it
    DIST_DIR.mkdir(exist_ok=True)
    
    # Run container
    # We map the current user so output files aren't owned by root
    uid = os.getuid()
    gid = os.getgid()
    
    # We mount the entire project root to /app
    # The container will run 'python scripts/build.py --local' inside
    
    cmd_run = [
        "podman", "run", "--rm",
        "-v", f"{PROJECT_ROOT}:/app:Z",
        "--user", f"{uid}:{gid}",
        image_name,
        "python", "scripts/build.py", "--local",
        "--name", binary_name
    ]
    
    if debug:
        cmd_run.append("--debug")

    try:
        subprocess.run(cmd_run, check=True)
        return 0
    except subprocess.CalledProcessError:
        print("Build inside Docker failed.")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="KuLo Build Script")
    parser.add_argument("--local", action="store_true", help="Build locally on host")
    parser.add_argument("--name", type=str, help="Output binary name")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--no-clean", action="store_true", help="Skip cleaning artifacts")
    parser.add_argument("--no-verify", action="store_true", help="Skip verification")
    
    args = parser.parse_args()
    
    binary_name = args.name or get_default_binary_name()

    if args.local:
        return build_locally(
            binary_name=binary_name,
            debug=args.debug,
            clean=not args.no_clean,
            verify=not args.no_verify
        )
    else:
        return build_in_docker(binary_name=binary_name, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())

