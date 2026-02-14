from __future__ import annotations


def main() -> int:
    try:
        from .gui_app import launch_gui
    except ImportError as exc:
        if "PySide6" in str(exc):
            print("GUI dependencies are missing. Install with: pip install -e \".[gui]\"")
            return 1
        raise
    return launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
