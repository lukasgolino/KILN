"""KILN (Keyed Implicit Language & Notation): smooth stylised 3D models written as text, built into glTF."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kiln")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0"
