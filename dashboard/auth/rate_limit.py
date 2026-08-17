"""Mecanismo ligero de rate limiting en memoria basado en ventana deslizante."""

import threading
import time
from collections import defaultdict


class InMemoryRateLimiter:
    """Limitador de frecuencia en memoria con algoritmo de sliding window."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._records = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Comprueba si la peticion es permitida.

        Retorna (permitido, retry_after_segundos).
        """
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            # Filtrar marcas de tiempo fuera de la ventana
            timestamps = [t for t in self._records[key] if t > window_start]
            if len(timestamps) >= self.max_requests:
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + self.window_seconds - now))
                self._records[key] = timestamps
                return False, retry_after

            timestamps.append(now)
            self._records[key] = timestamps
            return True, 0

    def reset(self, key: str | None = None):
        """Limpia registros (util para testing o desbloqueo manual)."""
        with self._lock:
            if key is None:
                self._records.clear()
            else:
                self._records.pop(key, None)
