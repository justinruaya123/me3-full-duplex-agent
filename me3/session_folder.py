"""Private, persistent flat work folders for local Pi chats."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid


class SessionFolder:
    file_limit = 64
    byte_limit = 16_384

    def __init__(self, root: Path, owner: str, chat: str):
        if not owner or not chat or len(chat) > 200:
            raise ValueError("Missing or invalid Pi chat identity")
        self.owner = owner
        key = hashlib.sha256((owner + "\0" + chat).encode()).hexdigest()
        self.path = root.resolve() / "workfolders" / key
        self.path.parent.mkdir(mode=0o700, exist_ok=True)
        with self._directory(create=True):
            pass

    @contextmanager
    def _directory(self, *, create=False):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        base = os.open(self.path.parent, flags)
        try:
            if create:
                try:
                    os.mkdir(self.path.name, mode=0o700, dir_fd=base)
                except FileExistsError:
                    pass
            folder = os.open(self.path.name, flags, dir_fd=base)
            try:
                yield folder
            finally:
                os.close(folder)
        finally:
            os.close(base)

    @staticmethod
    def valid(name):
        return (isinstance(name, str) and 0 < len(name.encode()) <= 128
                and not name.startswith(".") and name == name.strip()
                and name.isprintable() and "/" not in name and "\\" not in name)

    def names(self):
        names = []
        with self._directory() as folder, os.scandir(folder) as entries:
            for entry in entries:
                if not self.valid(entry.name):
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    names.append(entry.name)
                    if len(names) > self.file_limit:
                        raise ValueError("Work folder exceeds the 64-file listing limit")
        return sorted(names, key=str.casefold)

    def read(self, name):
        if not self.valid(name):
            raise ValueError("Use one visible filename in this chat's work folder")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with self._directory() as folder:
            try:
                fd = os.open(name, flags, dir_fd=folder)
            except OSError as exc:
                raise ValueError("File unavailable in this work folder") from exc
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Choose a regular file in this work folder")
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(self.byte_limit + 1)
            finally:
                os.close(fd)
        if len(data) > self.byte_limit or b"\0" in data:
            raise ValueError("Choose a UTF-8 text file of at most 16 KiB")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Choose a UTF-8 text file") from exc

    def save(self, name, text):
        if (not self.valid(name) or not text or "\0" in text
                or len(text.encode()) > self.byte_limit):
            raise ValueError("Use one visible filename and up to 16 KiB of text")
        if len(self.names()) >= self.file_limit:
            raise ValueError("Work folder file limit reached")
        with self._directory() as folder:
            tmp = "." + uuid.uuid4().hex
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=folder)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(text.encode())
                try:
                    os.link(tmp, name, src_dir_fd=folder, dst_dir_fd=folder)
                except FileExistsError as exc:
                    raise ValueError("That filename already exists. Choose a new name.") from exc
            finally:
                os.unlink(tmp, dir_fd=folder)

    def create_requested(self, name, content, request):
        """Only the operator can select the destination of a model-authored file."""
        if not self.valid(name):
            raise ValueError("Use a visible filename in this chat's work folder")
        instruction = (r"^(?:please\s+)?(?:create|write|save)\s+(?:a file (?:named|called)\s+)?"
                       + re.escape(name) + r"(?=$|[\s:=])")
        if not re.match(instruction, request, re.I):
            raise ValueError("Ask to create FILENAME followed by what it should contain")
        self.save(name, content)

    def command(self, text):
        """Handle explicit local operations before an inference request."""
        value = text.strip()
        listing = (r"(?:/files|(?:my|session) files(?: here)?|list (?:my |the )?files(?: here)?|what files "
                   r"(?:are here|do I have(?: here)?)|what are my files(?: here)?)")
        if re.fullmatch(listing + r"[.!?]?", value, re.I):
            names = self.names()
            return "Files in this chat: " + ", ".join(names) if names else "This chat's work folder is empty."
        match = re.fullmatch(r"(?:/read|read (?:the )?file|read)\s+(.+)", value, re.I)
        if match:
            name = self.spoken_name(match[1].rstrip(".?!"))
            if "." in name or value.startswith("/read ") or "file " in value or name in self.names():
                return self.read(name) or "The file is empty."
        match = re.fullmatch(r"(?:/save|save)\s+([^=\n]+?)\s*(?:=| as )\s*(.+)", value, re.I | re.S)
        if match:
            name = self.spoken_name(match[1])
            self.save(name, match[2])
            return "Saved " + name + " in this chat's work folder."
        return None

    @staticmethod
    def spoken_name(text):
        return re.sub(r"\s+dot\s+", ".", text.strip(), flags=re.I)

    def reference(self, question):
        """Answer file questions locally without intercepting worker requests."""
        question = self.spoken_name(question)
        inspection = (r"^(?:(?:please|can you|could you|would you)\s+)*"
                      r"(?:what|which|when|where|who|why|how|is|are|does|do|"
                      r"show|list|explain|summari[sz]e|describe|tell me)\b")
        if not re.match(inspection, question, re.I):
            return None
        about_folder = re.search(r"\b(?:files?|folder|directory)\b", question, re.I)
        if "." not in question.rstrip(".?!") and not about_folder and not re.search(
                r"\bsummari[sz]e\b", question, re.I):
            return None
        names = self.names()
        for name in names:
            if re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-]|\.\w)",
                         question, re.I):
                return {"filename": name, "text": self.read(name)}
        return {"filenames": names} if about_folder else None
