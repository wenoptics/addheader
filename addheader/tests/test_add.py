##############################################################################
# Copyright
# =========
# The Institute for the Design of Advanced Energy Systems Process Systems Engineering
# Framework (IDAES PSE Framework) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES), and is copyright (c) 2018-2019 by the
# software owners: The Regents of the University of California, through Lawrence
# Berkeley National Laboratory,  National Technology & Engineering Solutions of
# Sandia, LLC, Carnegie Mellon University, West Virginia University Research
# Corporation, et al.  All rights reserved.
#
# NOTICE.  This Software was developed under funding from the U.S. Department of
# Energy and the U.S. Government consequently retains certain rights. As such, the
# U.S. Government has been granted for itself and others acting on its behalf a
# paid-up, nonexclusive, irrevocable, worldwide license in the Software to
# reproduce, distribute copies to the public, prepare derivative works, and
# perform publicly and display publicly, and to permit other to do so. Copyright
# (C) 2018-2019 IDAES - All Rights Reserved
#
##############################################################################
"""
Tests for addheader.add module
"""
import sys
import pytest
import addheader
from addheader import add


class SetArgv:
    def __init__(self, *args):
        self._saved_argv = sys.argv
        self._argv = ["script"] + list(args)

    def __enter__(self):
        sys.argv = self._argv

    def __exit__(self, *ignored):
        sys.argv = self._saved_argv


def _make_source_tree(root):
    """Create this source tree::

        mypackage
            __init__.py
            foo.py
            bar.py
            tests/
                __init__.py
                test_foo.py
                test_bar.py
    """
    package = root / "mypackage"
    package.mkdir()
    for f in ("__init__.py", "foo.py", "bar.py"):
        fp = (package / f).open("w")
        if f[0] == "_":
            pass
        elif f[0] == "f":
            fp.write("   \n")  # test whitespace-only file
        else:
            fp.write("# Comment at top\n"
                     "import sys\n"
                     "\n"
                     "print('Hello, World!')\n")
    tests = package / "tests"
    tests.mkdir()
    for f in ("__init__.py", "test_foo.py", "test_bar.py"):
        (tests / f).open("w")


def test_file_finder(tmp_path):
    _make_source_tree(tmp_path)
    root = str(tmp_path.resolve())
    ff = add.FileFinder(root, glob_patterns=["*"])
    assert len(ff) == 8
    ff = add.FileFinder(root, glob_patterns=["*.py", "~test_*.py", "~__init__.py"])
    assert len(ff) == 2


def test_file_modifier(tmp_path):
    _make_source_tree(tmp_path)
    root = str(tmp_path.resolve())
    ff = add.FileFinder(root, glob_patterns=["*.py", "~test_*.py", "~__init__.py"])
    assert len(ff) == 2
    header_text = "\n   Header for\nall the files"
    fm = add.FileModifier(header_text)
    # add header to files
    for f in ff:
        detected = fm.replace(f)
        assert not detected
    ff.reset()
    # make sure on second pass nothing changes
    for f in ff:
        old_text = open(f).read()
        detected = fm.replace(f)
        assert detected
        new_text = open(f).read()
        assert old_text == new_text


def test_detect_files(tmp_path):
    _make_source_tree(tmp_path)
    root = str(tmp_path.resolve())
    # only foo
    ff = add.FileFinder(root, glob_patterns=["*.py", "~bar.py", "~test_*.py", "~__init__.py"])
    assert len(ff) == 1
    has_header, no_header = add.detect_files(ff)
    assert len(has_header) == 0
    assert no_header == [tmp_path / "mypackage" / "foo.py"]


def test_headers():
    import os
    root = os.path.dirname(addheader.__file__)
    ff = addheader.add.FileFinder(root, glob_patterns=["*.py", "~__init__.py"])
    has_header, missing_header = addheader.add.detect_files(ff)
    assert len(missing_header) == 0


def test_cli(tmp_path):
    _make_source_tree(tmp_path)
    with (tmp_path / "license.txt").open("w") as f:
        f.write("Sample license\n"
                "With some sample text\n")
    root, text = str(tmp_path / "mypackage"), str(tmp_path / "license.txt")
    with SetArgv(root, "-t", text):
        addheader.add.main()
    with SetArgv(root, "-r"):
        addheader.add.main()
    with SetArgv(root, "-n"):
        addheader.add.main()
    with SetArgv(root, "-t", text, "--sep", "=", "--comment", "//", "--sep-len", "80"):
        addheader.add.main()


def test_empty_ish(tmp_path):
    root = tmp_path
    empty_file = root / "empty.txt"
    text = "New Header\nOn the Block"
    for whitespace in "", "   ", "  \n", "\n", "\n\n", "#!/usr", "#!/usr\n", "#!/usr\n\n":
        print(f"whitespace = '{whitespace}'")
        empty_file.open("w").write(whitespace)
        fm = add.FileModifier(text)
        fm.replace(empty_file)
        contents = empty_file.open("r").read()
        expected_len = len(whitespace) + fm.header_len + 1
        # for magic that doesn't end in newline, extra newline inserted
        if whitespace.startswith("#") and not whitespace.endswith("\n"):
            expected_len += 1
        assert len(contents) == expected_len

