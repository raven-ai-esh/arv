"""New investigations use working models; old research keeps its original method."""
import os
from .store import Store
from .legacy_server import data_path


def build_server(path=None):
    path = path or data_path()
    historical = os.environ.get("ARV_COMPAT_VALIDATION") == "1"
    bound = os.environ.get("ARV_RESEARCH", "")
    if bound:
        store = Store(path)
        with store.db() as db:
            historical = store._research(db, bound).get("method") != "working_model"
    if historical:
        from .legacy_server import build_server as build
    else:
        from .working_server import build_server as build
    return build(path)


def main():
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
