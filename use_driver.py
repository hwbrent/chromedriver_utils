from typing import Iterable
from contextlib import contextmanager

from init import init


@contextmanager
def use_driver(chromedriver_path: str, args: Iterable[str]):
    """
    Creates a driver using the given params (passed to `init`) and yields
    it for use, quitting afterwards

    >>> with use_driver("/path/to/chromedriver") as driver:
    >>>    driver.get("https://www.google.com")
    >>>    ...
    """
    driver = init(chromedriver_path, args)
    try:
        yield driver
    finally:
        driver.quit()
