"""Install or transfer BMO from a source checkout. Run python3 setup.py --help."""
import sys

if __name__ == "__main__":
    # PEP 517 and setuptools also execute this file for package builds.
    if len(sys.argv) > 1 and sys.argv[1] not in {
        "install-bmo", "configure", "run", "check", "export-config", "import-config",
        "--help", "-h", "--no-prompt",
    }:
        from setuptools import setup
        setup()
    else:
        from scripts.bmo_setup import main
        main()
