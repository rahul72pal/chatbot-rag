import time
from contextlib import contextmanager
from typing import Generator, Callable
from uuid import UUID

@contextmanager
def measure_latency() -> Generator[Callable[[], float], None, None]:
    """Context manager to measure the elapsed execution time in seconds.
    
    Yields:
        A callable that returns the current elapsed time.
    """
    start_time = time.perf_counter()
    # Return a closure to compute current elapsed time
    yield lambda: time.perf_counter() - start_time


def is_valid_uuid4(uuid_string: str) -> bool:
    """Validates that a string is a valid UUID4.
    
    Args:
        uuid_string: The string to test.
        
    Returns:
        True if the string is a valid UUID4, False otherwise.
    """
    try:
        uuid_obj = UUID(uuid_string, version=4)
        # Ensure format matches exactly (handles capitalization and hyphens normalized output)
        return str(uuid_obj) == uuid_string.lower()
    except ValueError:
        return False
