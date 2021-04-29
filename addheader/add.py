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
Put a notice in the header of all files in a source code tree.

An existing notice will be replaced, and if there is no notice
encountered then one will be inserted. Detection of the notice
is exceedingly simple: if any line without a comment is encountered, from
the top of the file, before the standard "separator" of a long string
of comment characters, then the notice will be inserted. Likewise, the
"end" of the notice is either the same separator used for the beginning or
a line that is not commented.

For example, in the following he notice will be inserted between the
second and third lines::

    #!/usr/bin/env python
    # hello
    # <notice inserted here>
    import sys

In this file he notice will be inserted before the first line::

    # <notice inserted here>
    '''
    Top of the file comment
    '''
    import logging
"""
import argparse
from collections import deque
from fnmatch import fnmatch
import logging
import os
from pathlib import Path
import re
import shutil
import sys
from typing import List, Union, Optional
from uuid import uuid4

__author__ = "Dan Gunter (LBNL)"

_log = logging.getLogger(__name__)
_h = logging.StreamHandler()
_h.setFormatter(
    logging.Formatter(fmt="%(asctime)s [%(levelname)s] addheader: %(message)s")
)
_log.addHandler(_h)


def visit_files(finder, func):
    visited = []
    for f in finder:
        func(f)
        visited.append(f)
    return visited


def detect_files(finder):
    modifier = FileModifier()  # text is irrelevant
    has_header, no_header = [], []
    for f in finder:
        if modifier.detect(f):
            has_header.append(f)
        else:
            no_header.append(f)
    return has_header, no_header


class FileFinder(object):
    """Seek and ye shall find.

    Use this class as an iterator, e.g.::

        for path in FileFinder(..args..):
           <do something with 'path'>
    """

    DEFAULT_PATTERNS = ["*.py", "~__*"]

    def __init__(
        self, root: Union[str, Path], glob_patterns: Optional[List[str]] = None
    ):
        if not hasattr(root, "open"):  # not a Path-like
            root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"Root must be a directory: {root}")
        if glob_patterns is None:
            # use default patterns if none are given
            glob_patterns = self.DEFAULT_PATTERNS.copy()
        else:
            # eliminate empty patterns in input list
            glob_patterns = list(filter(None, glob_patterns))
        self._patterns = {"negative": [], "positive": []}
        for gp in glob_patterns:
            if gp[0] == "~":
                self._patterns["negative"].append(gp[1:])
            else:
                self._patterns["positive"].append(gp)

        self._root, self._q = root, None
        self.reset()

    def reset(self):
        self._q = deque()
        for pat in self._patterns["positive"]:
            self._find(pat)

    def __len__(self):
        return len(self._q)

    def _find(self, pattern: str):
        """Recursively find all files matching glob 'pattern' from `self._root`
        and add these files (as Path objects) to `self._q`.
        """
        for path in self._root.glob(f"**/{pattern}"):
            match_exclude = False
            for exclude in self._patterns["negative"]:
                if fnmatch(path.name, exclude):
                    match_exclude = True
                    break
            if not match_exclude:
                self._q.append(path)

    def __iter__(self):
        return self

    def __next__(self) -> str:
        try:
            return self._q.pop()
        except IndexError:
            raise StopIteration


class FileModifier:
    """Modify a file with a header."""

    DEFAULT_COMMENT = "#"
    DEFAULT_DELIM_CHAR = "#"
    DEFAULT_DELIM_LEN = 78
    DELIM_MINLEN = 10
    # File 'magic' allowed in first two lines before comment
    magic_expr = re.compile(
        r"^[ \t\f]*#" "(.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+|" "!/.*)"
    )

    def __init__(
        self,
        text: str = None,
        comment_prefix=DEFAULT_COMMENT,
        delim_char=DEFAULT_DELIM_CHAR,
        delim_len=DEFAULT_DELIM_LEN,
    ):
        """Constructor.

        Args:
            text: Text to place in header. Ignore for remove and detect functions.
            comment_prefix: Character(s) the start of a line that indicates a comment
            delim_char: Character to repeat for the delimiter line
            delim_len: Number of `delim_char` characters to put together to make a delimiter line
        """
        self._pfx = comment_prefix
        self._sep = comment_prefix + delim_char * delim_len
        self._minsep = comment_prefix + delim_char * self.DELIM_MINLEN
        if text is None:
            text = "..."
        lines = [l.strip() for l in text.split("\n")]
        self._txt = "\n".join([f"{self._pfx} {line}".strip() for line in lines])

    def replace(self, path: Path):
        """Modify header in the file at 'path'.

        Args:
            path: File to replace.

        Returns:

        """
        _log.info(f"Modify header in file: {path}")
        return self._process(path, mode="replace")

    def remove(self, path):
        """Remove header from the file at 'path'.

        Args:
            path: File to remove header from.

        Returns:

        """
        _log.info(f"Remove header from file: {path}")
        return self._process(path, mode="remove")

    def detect(self, path) -> bool:
        """Detect header in the file at 'path'.

        Args:
            path: File to remove header from.

        Returns:
            True if there was a header, else False
        """
        _log.info(f"Remove header from file: {path}")
        return self._process(path, mode="detect")

    def _process(self, path, mode) -> bool:
        # move input file to <name>.orig
        if mode == "detect":
            f = path.open("r", encoding="utf8")
            out, fname, wfname = None, None, None
        else:
            random_str = uuid4().hex
            fname = str(path.resolve())
            wfname = f"{fname}.orig.{random_str}"
            try:
                shutil.move(fname, wfname)
            except shutil.Error as err:
                _log.fatal(f"Unable to move file '{fname}' to '{wfname}': {err}")
                _log.error("Abort file modification loop")
                return False
            # re-open input filename as the output file
            f = open(wfname, "r", encoding="utf8")
            out = open(fname, "w", encoding="utf8")
        # re-create the file, modified
        state, lineno = "pre", 0
        detected, line_stripped = False, ""
        try:
            # Main loop
            for line in f:
                line_stripped = line.strip()
                if state == "pre":
                    if line_stripped.startswith(self._minsep):  # start of header
                        state = "header"
                    elif lineno < 3 and self.magic_expr.match(line_stripped):
                        if mode != "detect":
                            out.write(line)
                    else:
                        state = "post"  # no header, will copy rest of file
                    # if we changed state, write the header (or skip it)
                    if state != "pre" and mode == "replace":
                        self._write_header(out)
                    if state == "post" and mode != "detect":
                        # no header, so write last line of text below header
                        out.write(line)
                elif state == "header":
                    # none of the modes write the old header
                    if line_stripped.startswith(self._minsep):  # end of header
                        detected = True
                        state = "post"
                elif state == "post":
                    # replace/remove both copy all lines after header
                    if mode != "detect":
                        out.write(line)
                lineno += 1
        except UnicodeDecodeError as err:
            _log.error(f"File {path}:{lineno} error: {err}")
            _log.error(f"Previous line: {line_stripped}")
            if mode != "detect":
                _log.warning(
                    f"Restoring original file '{fname}'. You must manually fix it!"
                )
                out.close()
                f.close()
                shutil.move(wfname, fname)
        if state == "header":
            _log.error(f"Header started but did not end in file: {path}")
        if mode != "detect":
            # finalize the output
            out.close()
            f.close()
            # remove moved <name>.orig, the original input file
            os.unlink(wfname)
        return detected

    def _write_header(self, outfile):
        outfile.write(self._sep)
        outfile.write("\n")
        outfile.write(self._txt)
        outfile.write("\n")
        outfile.write(self._sep)
        outfile.write("\n")


# CLI usage

g_quiet = False


def tell_user(message):
    if not g_quiet:
        print(message)


def main() -> int:
    global g_quiet
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("root", help="Root path from which to find files")
    p.add_argument(
        "-t",
        "--text",
        help="File containing header text. "
        "Ignored if --dry-run or --remove options are given.",
    )
    p.add_argument(
        "-p",
        "--pattern",
        action="append",
        default=[],
        help="UNIX glob-style pattern of files to match (repeatable). "
        "Prefix a pattern with '~' to take complement. "
        "(default = *.py, ~__init__.py)",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry",
        help="Do not modify files, just show which files would be affected",
    )
    p.add_argument(
        "-r",
        "--remove",
        action="store_true",
        dest="remove",
        help="Remove headers from files, but do not replace them with anything",
    )
    p.add_argument("--comment",
                   help=f"Comment prefix (default='{FileModifier.DEFAULT_COMMENT})'")
    p.add_argument("--sep",
                   help=f"Separator character (default='{FileModifier.DEFAULT_DELIM_CHAR})'")
    p.add_argument("--sep-len",
                   type=int, default=-1,
                   help=f"Separator length (default={FileModifier.DEFAULT_DELIM_LEN})")
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        dest="vb",
        default=0,
        help="More verbose logging",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress all output")
    args = p.parse_args()

    # Set up logging from verbosity argument
    if args.quiet:
        _log.setLevel(logging.FATAL)
        g_quiet = True
    elif args.vb > 1:
        _log.setLevel(logging.DEBUG)
    elif args.vb > 0:
        _log.setLevel(logging.INFO)
    else:
        _log.setLevel(logging.WARN)

    # read notice from file
    notice_text = ""
    if args.remove:
        if args.text:
            tell_user(f"-r/--remove option given so text '{args.text}' will be ignored")
    elif args.dry:
        if args.text:
            tell_user(
                f"-d/--dry-run option given so text '{args.text}' will be ignored"
            )
    else:
        if not args.text:
            p.error(f"-t/--text is required to replace current header text")
        try:
            with open(args.text, "r") as f:
                notice_text = f.read()
        except Exception as err:
            p.error(f"Cannot read text file: {args.text}: {err}")

    # Check input patterns
    if len(args.pattern) == 0:
        patterns = ["*.py", "~__init__.py"]
    else:
        # sanity-check the input patterns
        for pat in args.pattern:
            if os.path.sep in pat:
                p.error('bad pattern "{}": must be a filename, not a path'.format(pat))
        patterns = args.pattern

    # Initialize file-finder
    finder = FileFinder(args.root, glob_patterns=patterns)
    if len(finder) == 0:
        _log.warning(
            'No files found from "{}" matching {}'.format(args.root, "|".join(patterns))
        )
        return 1

    # Find and replace files
    if args.dry:
        file_list = visit_files(finder, tell_user)
        plural = "s" if len(file_list) > 1 else ""
        tell_user(f"Found {len(file_list)} file{plural}")
    else:
        kwargs = {}
        if args.comment:
            kwargs["comment_prefix"] = args.comment
        if args.sep:
            kwargs["delim_char"] = args.sep[0]
        if args.sep_len > 0:
            if args.sep_len < FileModifier.DELIM_MINLEN:
                p.error(f"Separator length from '--sep-len' option must be >= {FileModifier.DELIM_MINLEN}")
            kwargs["delim_len"] = args.sep_len
        modifier = FileModifier(notice_text, **kwargs)
        modifier_func = modifier.remove if args.remove else modifier.replace
        file_list = visit_files(finder, modifier_func)
        plural = "s" if len(file_list) > 1 else ""
        tell_user(f"Modified {len(file_list)} file{plural}")
        if _log.isEnabledFor(logging.INFO):
            tell_user(f"Files: {', '.join(map(str, file_list))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
