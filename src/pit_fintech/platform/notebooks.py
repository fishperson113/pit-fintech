"""Execute notebooks in memory to verify they remain reproducible and output-free in Git."""

from __future__ import annotations

from pathlib import Path


def verify_notebooks(project_root: Path, timeout_seconds: int = 300) -> list[Path]:
    try:
        import nbformat
        from nbclient import NotebookClient
    except ImportError as exc:  # pragma: no cover - explicit developer-environment failure
        raise RuntimeError("notebook verification requires the dev dependency group") from exc

    paths = sorted((project_root / "notebooks").glob("*.ipynb"))
    for path in paths:
        notebook = nbformat.read(path, as_version=4)
        client = NotebookClient(
            notebook,
            timeout=timeout_seconds,
            kernel_name="python3",
            resources={"metadata": {"path": str(project_root)}},
        )
        client.execute()
    return paths
