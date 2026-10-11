import os
import tomllib


def get_version() -> str:
    """
    The version of Lithica, from pyproject.toml. The images run the source
    without installing the package, so there is no installed metadata to ask;
    the file is next to the package in a checkout and in the images alike.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pyproject.toml")
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)["project"]["version"]
    except (OSError, KeyError):
        return "unknown"
