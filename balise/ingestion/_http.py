"""Téléchargement HTTP en flux, partagé par les modules d'ingestion de fichiers volumineux."""

from __future__ import annotations

import time
from pathlib import Path

import requests


class DownloadError(Exception):
    """Échec de téléchargement après épuisement des tentatives."""


def download_stream(
    url: str,
    dest_path: Path,
    timeout: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with requests.get(url, timeout=timeout, stream=True) as response:
                response.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            return
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * attempt)
    raise DownloadError(
        f"Échec de téléchargement de {url} après {max_retries} tentatives : {last_error}"
    ) from last_error
