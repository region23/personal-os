#!/usr/bin/env python3
"""Create a Personal OS workspace from local, portable text templates."""

import argparse
from datetime import date
import os
from pathlib import Path
import re
import stat
import sys
from typing import List, Optional, Sequence, Tuple


class BootstrapError(Exception):
    """A setup problem that can be reported without a traceback."""


def validate_date(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise BootstrapError("Дата должна иметь формат ГГГГ-ММ-ДД.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise BootstrapError("Указана несуществующая дата.") from None
    return value


def _check_target(target: Path) -> bool:
    """Return whether the target exists, accepting only an empty real directory."""
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        raise BootstrapError("Папка назначения не может быть символической ссылкой.")
    if not stat.S_ISDIR(info.st_mode):
        raise BootstrapError("Путь назначения уже занят файлом.")
    with os.scandir(target) as entries:
        if next(entries, None) is not None:
            raise BootstrapError("Папка назначения должна быть полностью пустой, включая скрытые файлы.")
    return True


def _prepare_templates(
    root: Path, run_date: str, timezone: str
) -> Tuple[List[Path], List[Tuple[Path, bytes]]]:
    """Read and validate every input before the destination is touched."""
    try:
        root_info = root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise BootstrapError("Источник шаблонов должен быть обычной папкой.")
    except OSError:
        raise BootstrapError("Не удалось открыть папку шаблонов.") from None

    directories = []
    files = []

    def visit(folder: Path) -> None:
        try:
            with os.scandir(folder) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            raise BootstrapError("Не удалось прочитать папку шаблонов.") from None
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root)
            try:
                if entry.is_symlink():
                    raise BootstrapError("Символические ссылки в шаблонах запрещены.")
                if entry.is_dir(follow_symlinks=False):
                    directories.append(relative)
                    visit(path)
                elif entry.is_file(follow_symlinks=False):
                    contents = path.read_bytes().decode("utf-8")
                    # Reject unknown and malformed placeholders before substituting.
                    remaining = contents.replace("{{DATE}}", "").replace("{{TIMEZONE}}", "")
                    if "{{" in remaining or "}}" in remaining:
                        raise BootstrapError("В шаблонах есть неизвестный или незавершённый токен.")
                    rendered = contents.replace("{{DATE}}", run_date).replace("{{TIMEZONE}}", timezone)
                    if "{{" in rendered or "}}" in rendered:
                        raise BootstrapError("После подстановки остались токены шаблона.")
                    files.append((relative, rendered.encode("utf-8")))
                else:
                    raise BootstrapError("В шаблонах разрешены только обычные текстовые файлы и папки.")
            except (OSError, UnicodeError):
                raise BootstrapError("Не удалось прочитать текстовый шаблон в UTF-8.") from None

    visit(root)
    if not files:
        raise BootstrapError("В папке шаблонов нет файлов.")
    return directories, files


# Each record contains the identity of an entry created during this run. This
# prevents rollback from deleting a replacement placed there by another process.
CreatedEntry = Tuple[Path, int, int, bool]


def _record(path: Path, info: os.stat_result, is_directory: bool) -> CreatedEntry:
    return path, info.st_dev, info.st_ino, is_directory


def _rollback(created: List[CreatedEntry]) -> bool:
    complete = True
    for path, device, inode, is_directory in reversed(created):
        try:
            info = path.lstat()
            if (info.st_dev, info.st_ino) != (device, inode):
                complete = False
                continue
            if is_directory:
                path.rmdir()
            else:
                path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            complete = False
    return complete


def _create_target(target: Path, created: List[CreatedEntry]) -> None:
    missing = []
    current = target
    while True:
        try:
            current.lstat()
            break
        except FileNotFoundError:
            missing.append(current)
            current = current.parent
    for folder in reversed(missing):
        folder.mkdir()
        created.append(_record(folder, folder.lstat(), True))


def bootstrap(
    target: Path,
    *,
    run_date: str,
    timezone: str = "❓",
    template_root: Optional[Path] = None,
) -> int:
    """Create files exclusively; return their count or roll back this run."""
    validate_date(run_date)
    target = Path(os.path.abspath(os.fspath(target)))
    root = (
        Path(template_root)
        if template_root is not None
        else Path(__file__).resolve().parent.parent / "assets" / "starter"
    )
    created = []
    try:
        _check_target(target)
        directories, files = _prepare_templates(root, run_date, timezone)
        # Template validation can take time; check again before the first write.
        if not _check_target(target):
            _create_target(target, created)
        for relative in directories:
            folder = target / relative
            folder.mkdir()
            created.append(_record(folder, folder.lstat(), True))
        for relative, contents in files:
            destination = target / relative
            with destination.open("xb") as stream:
                created.append(_record(destination, os.fstat(stream.fileno()), False))
                stream.write(contents)
    except BaseException as error:
        rolled_back = _rollback(created)
        if isinstance(error, OSError):
            message = "Не удалось создать Personal OS: проверь путь и права доступа."
            if not rolled_back:
                message += " Часть созданных файлов не удалось убрать; проверь папку назначения."
            raise BootstrapError(message) from None
        raise
    return len(files)


def _date_argument(value: str) -> str:
    try:
        return validate_date(value)
    except BootstrapError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="новая или полностью пустая папка назначения")
    parser.add_argument("--date", required=True, type=_date_argument, help="дата настройки: ГГГГ-ММ-ДД")
    parser.add_argument("--timezone", default="❓", help="часовой пояс пользователя; по умолчанию: ❓")
    arguments = parser.parse_args(argv)
    try:
        count = bootstrap(arguments.target, run_date=arguments.date, timezone=arguments.timezone)
    except BootstrapError as error:
        print("Ошибка: " + str(error), file=sys.stderr)
        return 1
    print("Создано файлов: {}. Папка: {}".format(count, arguments.target.absolute()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
