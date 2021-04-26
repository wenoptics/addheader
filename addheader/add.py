#!/usr/bin/env python
##############################################################################
# Copyright
# =========
#
# Institute for the Design of Advanced Energy Systems Process Systems Engineering
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
from glob import glob, fnmatch
import logging
import os
import re
import shutil
import sys
from uuid import uuid4

__author__ = "Dan Gunter (LBNL)"

_log = logging.getLogger(__name__)
_h = logging.StreamHandler()
_h.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] addheader: %(message)s"))
_log.addHandler(_h)


def modify_files(finder, modifier, **flags):
    """Main function called for command-line usage"""
    return _visit_files(finder, modifier.modify, **flags)


def print_files(finder):
    """Print the files."""
    return _visit_files(finder, print)


def _visit_files(finder, func, **kwargs):
    visited = []
    while True:
        try:
            f = finder.get()
        except IndexError:
            break
        func(f, **kwargs)
        visited.append(f)
    return visited


class FileFinder(object):
    """Seek and ye shall find."""

    def __init__(self, root: str, glob_pat=None):
        if not os.path.isdir(root):
            raise FileNotFoundError('Root directory "{}"'.format(root))
        glob_pat = ["*.py"] if glob_pat is None else glob_pat
        neg_pat, pos_pat = [], []
        for p in glob_pat:
            if not p:
                pass
            if p[0] == "~":
                neg_pat.append(p[1:])
                _log.info("Negative pattern: {}".format(p[1:]))
            else:
                pos_pat.append(p)
                _log.info("Positive pattern: {}".format(p[1:]))
        self._root = root
        self._q = deque()
        for pat in pos_pat:
            self._find(pat, neg_pat)

    def __len__(self):
        return len(self._q)

    def _find(self, glob_pat, neg_pat):
        pat = os.path.join(self._root, "**", glob_pat)
        if neg_pat:
            # need to check each file, to eliminate bad ones
            for fpath in glob(pat, recursive=True):
                f, ok = os.path.basename(fpath), True
                # eliminate any that match a negative pattern
                for np in neg_pat:
                    _log.debug("Match file {} to pattern {}".format(f, np))
                    if fnmatch.fnmatchcase(f, np):
                        ok = False
                        break
                if ok:
                    self._q.append(fpath)
        else:
            # just grab all files
            self._q.extend(glob(pat, recursive=True))

    def get(self) -> str:
        item = self._q.pop()
        return item


class FileModifier(object):
    comment_pfx = "#"
    comment_sep = comment_pfx * 78
    comment_minsep = comment_pfx * 10

    def __init__(self, text: str):
        lines = [l.strip() for l in text.split("\n")]
        self._txt = "\n".join(
            ["{} {}".format(self.comment_pfx, l).strip() for l in lines]
        )

    def modify(self, fname: str, remove=False):
        _log.info("file={}".format(fname))
        # move input file to <name>.orig
        random_str = uuid4().hex
        wfname = f"{fname}.orig.{random_str}"
        try:
            shutil.move(fname, wfname)
        except shutil.Error as err:
            _log.fatal(f"Unable to move file '{fname}' to '{wfname}': {err}")
            _log.error("Abort file modification loop")
            return
        # re-open input filename as the output file
        f = open(wfname, "r", encoding="utf8")
        out = open(fname, "w", encoding="utf8")
        # re-create the file, modified
        state = "head"
        if remove:
            for line in f:
                if state == "head":
                    if line.strip().startswith(self.comment_minsep):
                        state = "copyright"
                        continue
                    else:
                        out.write(line)
                elif state == "copyright":
                    if line.strip().startswith(self.comment_minsep):
                        state = "code"
                else:
                    out.write(line)
        else:
            lineno = 0
            ex = re.compile(
                r"^[ \t\f]*#" "(.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+|" "!/.*)"
            )

            def write_copyright():
                out.write("{}\n".format(self.comment_sep))
                out.write(self._txt)
                out.write("\n{}\n".format(self.comment_sep))

            line = ""
            try:
                for line in f:
                    lineno += 1
                    sline = line.strip()
                    if state == "head":
                        if sline.startswith(self.comment_minsep):
                            state = "copyright"  # skip past this
                        elif lineno < 3 and ex.match(sline):
                            out.write(line)
                        else:
                            state = "text"
                            write_copyright()
                            out.write(line)
                    elif state == "copyright":
                        if sline.startswith(self.comment_minsep):
                            state = "text"
                            write_copyright()
                    elif state == "text":
                        out.write(line)
            except UnicodeDecodeError as err:
                _log.error(f"File {fname}:{lineno} error: {err}")
                _log.error(f"Previous line: {line}")
                _log.warning(
                    f"Restoring original file '{fname}'. You must manually fix it!"
                )
                out.close()
                f.close()
                shutil.move(wfname, fname)
                return
        # finalize the output
        out.close()
        f.close()
        # remove moved <name>.orig, the original input file
        f.close()
        os.unlink(wfname)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("root", help="Root path from which to find files")
    p.add_argument("text", help="File containing header text")
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
        help="Do not modify files, just show which files would be affected.",
    )
    p.add_argument(
        "-r",
        "--remove",
        action="store_true",
        dest="remove",
        help="Remove any existing headers",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        dest="vb",
        default=0,
        help="More verbose logging",
    )
    args = p.parse_args()

    # Set up logging from verbosity argument
    if args.vb > 1:
        _log.setLevel(logging.DEBUG)
    elif args.vb > 0:
        _log.setLevel(logging.INFO)
    else:
        _log.setLevel(logging.WARN)

    # read notice from file
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
    finder = FileFinder(args.root, glob_pat=patterns)
    if len(finder) == 0:
        _log.warning(
            'No files found from "{}" matching {}'.format(args.root, "|".join(patterns))
        )
        return 1

    # Find and modify files
    if args.dry:
        file_list = print_files(finder)
        print(f"Found {len(file_list)} files")
    else:
        modifier = FileModifier(notice_text)
        file_list = modify_files(finder, modifier, remove=args.remove)
        print(f"Modified {len(file_list)} files")
        if _log.isEnabledFor(logging.INFO):
            print(f"Files: {', '.join(file_list)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
