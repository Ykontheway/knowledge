"""No-follow directory traversal and exclusive creation, including external output."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from konwledge.replay.bundle import MAX_BYTES, ReplayError


@contextmanager
def parent_fd(path: Path, *, create: bool = False) -> Iterator[tuple[int, str]]:
    """Require existing parents for public files; private parents may be created."""
    # abspath removes dot components without resolving (and trusting) symlinks.
    absolute = Path(os.path.abspath(path))
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:-1]:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
            following = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = following
        yield descriptor, absolute.name
    except OSError:
        raise ReplayError("REPLAY_FILE_UNSAFE") from None
    finally:
        os.close(descriptor)


def ensure_absent(path: Path) -> None:
    with parent_fd(path) as (parent, name):
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ReplayError("REPLAY_OUTPUT_EXISTS")


def exclusive_write(path: Path, data: bytes, *, private: bool = False) -> None:
    """Never overwrite any existing file; O_EXCL also refuses dangling symlinks."""
    with parent_fd(path) as (parent, name):
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600 if private else 0o644,
                dir_fd=parent,
            )
        except FileExistsError:
            raise ReplayError("REPLAY_OUTPUT_EXISTS") from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            os.unlink(name, dir_fd=parent)
            raise ReplayError("REPLAY_FILE_UNSAFE") from None


def check_regular(path: Path) -> None:
    """Check the owned SQLite file without resolving a link or reading its contents."""
    with parent_fd(path) as (parent, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ReplayError("REPLAY_FILE_UNSAFE")
        finally:
            os.close(descriptor)


def read_static(path: Path) -> bytes:
    """Bounded regular-file read; no directories, FIFOs, links or writes."""
    with parent_fd(path) as (parent, name):
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ReplayError("REPLAY_FILE_UNSAFE")
                if info.st_size > MAX_BYTES:
                    raise ReplayError("REPLAY_SIZE_INVALID")
                return stream.read(MAX_BYTES + 1)
        except OSError:
            raise ReplayError("REPLAY_FILE_UNSAFE") from None
