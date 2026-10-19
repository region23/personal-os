"""From the package root: python3 -m unittest discover -s tests -v."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py"
SPEC = importlib.util.spec_from_file_location("personal_os_bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.templates = self.root / "templates"
        self.templates.mkdir()
        self.write_template("README.md", "Дата: {{DATE}}\nЧасовой пояс: {{TIMEZONE}}\n")
        self.target = self.root / "output"

    def write_template(self, relative, contents):
        path = self.templates / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def create(self, **options):
        return bootstrap.bootstrap(
            self.target, run_date="2026-10-17", template_root=self.templates, **options
        )

    def create_symlink(self, path, destination, **options):
        try:
            path.symlink_to(destination, **options)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symbolic links are unavailable in this environment: {}".format(error))

    def test_nested_templates_and_dotfiles_receive_explicit_values(self):
        self.write_template("nested/.gitignore", "private/\n{{DATE}}\n")
        self.assertEqual(self.create(timezone="Europe/Paris"), 2)
        self.assertEqual(
            (self.target / "README.md").read_text(encoding="utf-8"),
            "Дата: 2026-10-17\nЧасовой пояс: Europe/Paris\n",
        )
        self.assertEqual(
            (self.target / "nested/.gitignore").read_text(encoding="utf-8"),
            "private/\n2026-10-17\n",
        )

    def test_empty_existing_target_and_unknown_timezone_are_supported(self):
        self.target.mkdir()
        self.create()
        self.assertIn("Часовой пояс: ❓", (self.target / "README.md").read_text(encoding="utf-8"))

    def test_nonempty_target_preserves_existing_content_including_dotfiles(self):
        for name in ("notes.txt", ".private"):
            with self.subTest(name=name):
                self.target.mkdir()
                existing = self.target / name
                existing.write_bytes(b"original content")
                with self.assertRaises(bootstrap.BootstrapError):
                    self.create()
                self.assertEqual(existing.read_bytes(), b"original content")
                self.assertEqual(list(self.target.iterdir()), [existing])
                existing.unlink()
                self.target.rmdir()

    def test_existing_and_dangling_target_symlinks_are_refused(self):
        for destination in (self.templates, self.root / "does-not-exist"):
            with self.subTest(destination=destination.name):
                self.create_symlink(self.target, destination, target_is_directory=True)
                with self.assertRaises(bootstrap.BootstrapError):
                    self.create()
                self.assertTrue(self.target.is_symlink())
                self.target.unlink()

    def test_file_target_is_preserved(self):
        self.target.write_bytes(b"keep me")
        with self.assertRaises(bootstrap.BootstrapError):
            self.create()
        self.assertEqual(self.target.read_bytes(), b"keep me")

    def test_unknown_or_malformed_tokens_fail_before_creating_target(self):
        for contents in ("{{UNKNOWN}}", "{{DATE", "TIMEZONE}}"):
            with self.subTest(contents=contents):
                self.write_template("zz-last.txt", contents)
                with self.assertRaises(bootstrap.BootstrapError):
                    self.create()
                self.assertFalse(self.target.exists())

    def test_substitution_cannot_leave_new_tokens(self):
        with self.assertRaises(bootstrap.BootstrapError):
            self.create(timezone="{{UNKNOWN}}")
        self.assertFalse(self.target.exists())

    def test_template_symlinks_fail_before_creating_target(self):
        outside = self.root / "outside.txt"
        outside.write_text("keep me", encoding="utf-8")
        self.create_symlink(self.templates / "zz-link", outside)
        with self.assertRaises(bootstrap.BootstrapError):
            self.create()
        self.assertFalse(self.target.exists())
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep me")

    def test_non_utf8_template_fails_before_creating_target(self):
        (self.templates / "zz-binary").write_bytes(b"\xff\x00")
        with self.assertRaises(bootstrap.BootstrapError):
            self.create()
        self.assertFalse(self.target.exists())

    def test_template_read_failure_leaves_existing_empty_target_untouched(self):
        self.target.mkdir()
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("denied")):
            with self.assertRaises(bootstrap.BootstrapError):
                self.create()
        self.assertTrue(self.target.is_dir())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_write_failure_rolls_back_own_files_and_preserves_existing_target(self):
        self.write_template("nested/last.txt", "second output")
        original_open = Path.open

        class FailedWrite:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *arguments):
                return self.stream.__exit__(*arguments)

            def fileno(self):
                return self.stream.fileno()

            def write(self, contents):
                self.stream.write(contents[:1])
                self.stream.flush()
                raise OSError("simulated failure after a partial write")

        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.target.mkdir()

                def fail_second_output(path, mode="r", *args, **kwargs):
                    stream = original_open(path, mode, *args, **kwargs)
                    if path == self.target / "nested/last.txt" and mode == "xb":
                        return FailedWrite(stream)
                    return stream

                with mock.patch.object(Path, "open", fail_second_output):
                    with self.assertRaises(bootstrap.BootstrapError):
                        self.create()
                self.assertEqual(self.target.exists(), existing)
                if existing:
                    self.assertEqual(list(self.target.iterdir()), [])
                    self.target.rmdir()

    def test_file_appearing_during_setup_is_neither_overwritten_nor_removed(self):
        self.target.mkdir()
        original_open = Path.open
        collided = self.target / "README.md"

        def add_concurrent_file(path, mode="r", *args, **kwargs):
            if path == collided and mode == "xb":
                with original_open(path, "wb") as stream:
                    stream.write(b"created by another process")
            return original_open(path, mode, *args, **kwargs)

        with mock.patch.object(Path, "open", add_concurrent_file):
            with self.assertRaises(bootstrap.BootstrapError):
                self.create()
        self.assertEqual(collided.read_bytes(), b"created by another process")

    def test_failure_removes_new_parent_directories(self):
        self.target = self.root / "new-parent" / "new-child" / "output"
        original_open = Path.open

        def deny_output(path, mode="r", *args, **kwargs):
            if mode == "xb":
                raise PermissionError("simulated destination write failure")
            return original_open(path, mode, *args, **kwargs)

        with mock.patch.object(Path, "open", deny_output):
            with self.assertRaises(bootstrap.BootstrapError):
                self.create()
        self.assertFalse((self.root / "new-parent").exists())
        self.assertTrue(self.templates.is_dir())

    def test_invalid_and_missing_cli_dates_never_create_target(self):
        for arguments in ([], ["--date", "2026-02-30"], ["--date", "20261017"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(self.target), *arguments],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.target.exists())

    def test_bundled_starter_creates_base_skills_without_tokens(self):
        bootstrap.bootstrap(self.target, run_date="2026-10-17", timezone="Europe/Moscow")
        for relative in [
            "AGENTS.md",
            "README.md",
            "now.md",
            "me/README.md",
            ".agents/skills/inbox/SKILL.md",
            ".agents/skills/weekly-review/SKILL.md",
        ]:
            self.assertTrue((self.target / relative).is_file(), relative)
        for path in self.target.rglob("*"):
            if path.is_file():
                self.assertNotIn("{{", path.read_text(encoding="utf-8"), path)

    def test_valid_leap_day_is_accepted(self):
        self.assertEqual(bootstrap.validate_date("2024-02-29"), "2024-02-29")


if __name__ == "__main__":
    unittest.main()
