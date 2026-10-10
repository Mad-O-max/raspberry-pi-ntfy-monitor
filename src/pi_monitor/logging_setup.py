import logging


def configure(level: str) -> None:
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
