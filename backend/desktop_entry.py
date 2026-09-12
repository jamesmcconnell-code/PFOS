"""Frozen desktop API entry point; never start a development reloader."""
from app.desktop_runtime import main

if __name__ == '__main__':
    main()
