#!/usr/bin/env python3
"""Build script for creating KuLo standalone binaries.

This script uses PyInstaller to create a single self-contained executable
for Linux platforms (amd64 and arm64).

Usage:
    # Build for current platform
    python scripts/build.py

    # Build with specific name
    python scripts/build.py --name kulo-linux-amd64

    # Build in debug mode (shows console output)
    python scripts/build.py --debug
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def get_default_binary_name() -> str:
    """Get the default binary name based on platform.

    Returns:
        Binary name string (e.g., 'kulo-linux-amd64').
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize architecture names
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    arch = arch_map.get(machine, machine)

    return f"kulo-{system}-{arch}"


def clean_build_artifacts() -> None:
    """Remove previous build artifacts."""
    for directory in [BUILD_DIR, DIST_DIR]:
        if directory.exists():
            print(f"Cleaning {directory}...")
            shutil.rmtree(directory)


def run_pyinstaller(
    binary_name: str,
    debug: bool = False,
    one_file: bool = True,
) -> bool:
    """Run PyInstaller to create the executable.

    Args:
        binary_name: Name for the output binary.
        debug: Whether to build in debug mode.
        one_file: Whether to create a single file executable.

    Returns:
        True if build succeeded, False otherwise.
    """
    # PyInstaller arguments
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", binary_name,
        "--clean",
        "--noconfirm",
    ]

    if one_file:
        args.append("--onefile")

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

    print(f"Building {binary_name}...")
    print(f"Command: {' '.join(args)}")

    try:
        result = subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=not debug,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Build failed with exit code {e.returncode}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return False


def verify_binary(binary_name: str) -> bool:
    """Verify the built binary works.

    Args:
        binary_name: Name of the binary to verify.

    Returns:
        True if verification passed, False otherwise.
    """
    binary_path = DIST_DIR / binary_name

    if not binary_path.exists():
        print(f"Binary not found at {binary_path}")
        return False

    print(f"Verifying {binary_path}...")

    try:
        result = subprocess.run(
            [str(binary_path), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print(f"Version output: {result.stdout.strip()}")
            return True
        else:
            print(f"Binary exited with code {result.returncode}")
            print(f"STDERR: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("Binary timed out during verification")
        return False
    except Exception as e:
        print(f"Verification failed: {e}")
        return False


def print_build_info(binary_name: str) -> None:
    """Print build summary information.

    Args:
        binary_name: Name of the built binary.
    """
    binary_path = DIST_DIR / binary_name

    if binary_path.exists():
        size_mb = binary_path.stat().st_size / (1024 * 1024)
        print()
        print("=" * 60)
        print("BUILD SUCCESSFUL")
        print("=" * 60)
        print(f"Binary: {binary_path}")
        print(f"Size: {size_mb:.2f} MB")
        print()
        print("To test the binary:")
        print(f"  {binary_path} --help")
        print()
        print("To install system-wide:")
        print(f"  sudo cp {binary_path} /usr/local/bin/kulo")
        print("=" * 60)


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for the build script.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        description="Build KuLo standalone binary using PyInstaller",
    )

    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Output binary name (default: auto-detect based on platform)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build in debug mode with verbose output",
    )

    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Don't clean previous build artifacts",
    )

    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip binary verification after build",
    )

    return parser


def main() -> int:
    """Main entry point for the build script.

    Returns:
        Exit code (0 for success).
    """
    parser = create_parser()
    args = parser.parse_args()

    # Determine binary name
    binary_name = args.name or get_default_binary_name()
    print(f"Building KuLo as: {binary_name}")

    # Check dependencies
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found. Install with: uv pip install pyinstaller")
        return 1

    # Clean if requested
    if not args.no_clean:
        clean_build_artifacts()

    # Run build
    if not run_pyinstaller(binary_name, debug=args.debug):
        return 1

    # Verify if requested
    if not args.no_verify:
        if not verify_binary(binary_name):
            print("Warning: Binary verification failed")
            # Don't fail the build, just warn

    # Print summary
    print_build_info(binary_name)

    return 0


if __name__ == "__main__":
    sys.exit(main())

