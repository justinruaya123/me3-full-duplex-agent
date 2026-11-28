"""Bounded UTF-8 source reads for a locally selected file, tree or ZIP."""

import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path, PureWindowsPath
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from me3.file_visual import VISUAL_SUFFIXES

SUFFIXES = VISUAL_SUFFIXES | {
    ".tex",
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".csv",
    ".tsv",
}
FILE_BYTES = 4 * 1024 * 1024
TOTAL_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 4096
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def file_limit(name):
    return TOTAL_BYTES if Path(name).suffix.lower() == ".pdf" else FILE_BYTES


def selected_path(path):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Select a regular file or directory, rather than a link")
    return path.resolve(strict=True)


def name_issue(name):
    parts = name.split("/")
    if (
        not name.isprintable()
        or "\\" in name
        or PureWindowsPath(name).drive
        or any(not part or part.startswith(".") for part in parts)
    ):
        return "hidden or unsafe path"
    if Path(name).suffix.lower() not in SUFFIXES:
        return "unsupported format"
    return ""


@contextmanager
def regular_file(name, *, directory=None):
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    with os.fdopen(os.open(name, flags, dir_fd=directory), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Source must be a regular file with one hard link")
        yield stream, info


class Source:
    def __init__(self, path, stack):
        self.path = path
        self.directory = None
        self.archive = None
        if path.is_dir():
            self.directory = os.open(path, DIR_FLAGS)
            stack.callback(os.close, self.directory)
        elif path.suffix.lower() == ".zip":
            stream, info = stack.enter_context(regular_file(path))
            if info.st_size > TOTAL_BYTES:
                raise ValueError("ZIP exceeds the 64 MiB archive limit")
            self.archive = stack.enter_context(ZipFile(stream))
            if len(self.archive.infolist()) > MAX_ENTRIES:
                raise ValueError("ZIP exceeds the entry limit")

    def entries(self):
        if self.archive is not None:
            for ordinal, info in enumerate(self.archive.infolist()):
                if info.is_dir():
                    continue
                issue = name_issue(info.filename)
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG):
                    issue = "link or special file"
                elif info.flag_bits & 1:
                    issue = "encrypted"
                elif info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    issue = "unsupported compression"
                elif info.file_size > file_limit(info.filename):
                    issue = f"member exceeds {file_limit(info.filename) >> 20} MiB"
                yield info.filename, ordinal, issue
        elif self.directory is not None:
            yield from self._walk(self.directory, "", [0], 0)
        else:
            yield self.path.name, -1, name_issue(self.path.name)

    def _walk(self, fd, prefix, count, depth):
        if depth > 32:
            raise ValueError("Directory tree exceeds the depth limit")
        with os.scandir(fd) as entries:
            for entry in entries:
                count[0] += 1
                if count[0] > MAX_ENTRIES:
                    raise ValueError("Directory tree exceeds the entry limit")
                name = prefix + entry.name
                if entry.name.startswith("."):
                    yield name, -1, "hidden"
                elif entry.is_dir(follow_symlinks=False):
                    child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                    try:
                        yield from self._walk(child, name + "/", count, depth + 1)
                    finally:
                        os.close(child)
                elif entry.is_file(follow_symlinks=False):
                    yield name, -1, name_issue(name)
                else:
                    yield name, -1, "link or special file"

    def read(self, name, ordinal):
        if name_issue(name):
            raise ValueError("Unsupported source name")
        if self.archive is not None:
            members = self.archive.infolist()
            if not 0 <= ordinal < len(members) or members[ordinal].filename != name:
                raise ValueError("Archive member changed; rebuild the index")
            with self.archive.open(members[ordinal]) as stream:
                data = stream.read(file_limit(name) + 1)
        else:
            with ExitStack() as stack:
                parent = self.directory
                if parent is None:
                    if self.path.name != name:
                        raise ValueError("File changed; rebuild the index")
                    filename = self.path
                else:
                    *parents, filename = name.split("/")
                    for part in parents:
                        parent = os.open(part, DIR_FLAGS, dir_fd=parent)
                        stack.callback(os.close, parent)
                stream, info = stack.enter_context(
                    regular_file(filename, directory=parent)
                )
                if info.st_size > file_limit(name):
                    raise ValueError(f"member exceeds {file_limit(name) >> 20} MiB")
                data = stream.read(file_limit(name) + 1)
        if len(data) > file_limit(name):
            raise ValueError(f"member exceeds {file_limit(name) >> 20} MiB")
        return data
