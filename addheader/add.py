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
Put a header in all files in a source code tree.

An existing header will be replaced, and if there is no header
encountered then one will be inserted. The new header is inserted
after the first non-file-magic line in the file. Empty files and
files that are only whitespace are ignored by default.

For example, in the following the notice will be inserted between the
first and second line::

    #!/usr/bin/env python
    # hello
    import sys

to look like this::

    #!/usr/bin/env python
    ###############################
    # header inserted here
    ###############################
    # hello
    import sys

In this file the header will be inserted before the first line::

    '''
    This module does things.
    '''
    import logging

to look like this::
    
    ###############################
    # header inserted here
    ###############################
    '''
    This module does things.
    '''
    import logging
    

"""
# stdlib
import argparse
import json
from fnmatch import fnmatch

try:
    from importlib.metadata import version
except ImportError:
    from importlib_metadata import version
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import List, Union, Optional
from uuid import uuid4

# third-party
import yaml
from yaml import Loader

# For working with Jupyter notebooks
try:
    import nbformat
except ImportError:
    nbformat = None


__author__ = "Dan Gunter (LBNL)"

_log = logging.getLogger(__name__)
_h = logging.StreamHandler()
_h.setFormatter(
    logging.Formatter(fmt="%(asctime)s [%(levelname)s] addheader: %(message)s")
)
_log.addHandler(_h)

DEFAULT_CONF = "addheader.cfg"


class FileFinder(object):
    """Seek and ye shall find.

    Iterate over one of these attributes to get the files:

        * `files` = Text files
        * `notebooks` = Jupyter Notebooks
    """

    DEFAULT_PATTERNS = ["*.py", "~__*"]
    DEFAULT_PATH_EXCLUDE = [".?*"]

    def __init__(
        self,
        root: Union[str, Path],
        glob_patterns: Optional[List[str]] = None,
        path_exclude: Optional[List[str]] = None,
        jupyter_ext: Optional[str] = None,
    ):
        if not hasattr(root, "open"):  # not a Path-like
            root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"Root '{root}' must be a directory")
        if glob_patterns is None:
            # use default patterns if none are given
            glob_patterns = self.DEFAULT_PATTERNS.copy()
        else:
            # eliminate empty patterns in input list
            glob_patterns = list(filter(None, glob_patterns))
        self._path_exclude = path_exclude or self.DEFAULT_PATH_EXCLUDE.copy()
        self._patterns = {"negative": [], "positive": []}
        for gp in glob_patterns:
            if gp[0] == "~":
                self._patterns["negative"].append(gp[1:])
            else:
                self._patterns["positive"].append(gp)

        # If Jupyter notebooks are enabled, add the Jupyter extension
        if jupyter_ext:
            self._jupyter_ext = jupyter_ext
            self._patterns["positive"].append(f"*{self._jupyter_ext}")
        else:
            self._jupyter_ext = None

        self._root, self._q, self._jupyter_q = root, None, None
        self.reset()

    def reset(self):
        self._q = []
        if self._jupyter_ext:
            self._jupyter_q = []
        for pat in self._patterns["positive"]:
            self._find(pat)

    def __len__(self):
        jn = len(self._jupyter_q) if self._jupyter_q else 0
        tn = len(self._q)
        return tn + jn

    def _find(self, pattern: str):
        """Recursively find all files matching glob 'pattern' from `self._root`
        and add these files (as Path objects) to `self._q`.
        """
        for path in self._root.glob(f"**/{pattern}"):
            _log.debug(f"Checking file: {path.name}")
            match_exclude = False
            for exclude in self._patterns["negative"]:
                if fnmatch(path.name, exclude):
                    match_exclude = True
                    break
            spath = str(path)
            for excludep in self._path_exclude:
                if fnmatch(spath, excludep):
                    match_exclude = True
                    break
            if not match_exclude:
                if self._jupyter_ext and path.name.endswith(self._jupyter_ext):
                    self._jupyter_q.append(path)
                    _log.debug(f"Notebook matched: {path.name}")
                else:
                    self._q.append(path)
                    _log.debug(f"File matched: {path.name}")

    @property
    def files(self):
        return self._q

    @property
    def notebooks(self):
        return self._jupyter_q


def visit_files(files, func):
    visited = []
    if files:
        for f in files:
            func(f)
            visited.append(f)
    return visited


def detect_files(finder: FileFinder):
    modifier = TextFileModifier()  # text is irrelevant
    has_header, no_header = [], []
    for f in finder.files:
        if modifier.detect(f):
            has_header.append(f)
        else:
            no_header.append(f)
    if finder.notebooks:
        modifier = JupyterFileModifier()
        for f in finder.notebooks:
            if modifier.detect(f):
                has_header.append(f)
            else:
                no_header.append(f)
    return has_header, no_header


class FileModifier:
    EMPTY_TEXT = "..."  # text used if none is given
    DEFAULT_COMMENT = "#"
    DEFAULT_DELIM_CHAR = "#"
    DEFAULT_DELIM_LEN = 78
    DELIM_MINLEN = 10
    LINESEP = "\n"

    def __init__(
        self,
        text: str = None,
        comment_prefix=DEFAULT_COMMENT,
        delim_char=DEFAULT_DELIM_CHAR,
        delim_len=DEFAULT_DELIM_LEN,
        add_trailing_linesep=True,
        empty_files=False,
    ):
        """Constructor.

        Args:
            text: Text to place in header. Ignore for remove and detect functions.
            comment_prefix: Character(s) the start of a line that indicates a comment
            delim_char: Character to repeat for the delimiter line
            delim_len: Number of `delim_char` characters to put together to make a delimiter line
        """
        self._trail = add_trailing_linesep
        self._empty = empty_files
        self._pfx = comment_prefix
        self._sep = comment_prefix + delim_char * delim_len
        self._minsep = comment_prefix + delim_char * self.DELIM_MINLEN
        if text is None:
            text = self.EMPTY_TEXT
        # break text into lines and prefix each
        lines = [l.strip() for l in text.split(self.LINESEP)]
        self._lines = [f"{self._pfx} {line}".strip() for line in lines]
        self._num_text_lines = len(self._lines)
        # frame lines with separator
        self._lines.insert(0, self._sep)
        self._lines.append(self._sep)

    @property
    def sep_len(self) -> int:
        """Length of separator line (including comment characters, but not newline)"""
        return len(self._sep)

    @property
    def header_len(self) -> int:
        """Length of entire header text"""
        return sum((len(x) for x in self._lines)) + 2 + self._num_text_lines

    def replace(self, path: Path):
        """Modify header in the file at 'path'.

        Args:
            path: File to replace.

        Returns:

        """
        _log.debug(f"Replace header in file: {path}")
        return self._process(path, mode="replace")

    def remove(self, path):
        """Remove header from the file at 'path'.

        Args:
            path: File to remove header from.

        Returns:

        """
        _log.debug(f"Remove header from file: {path}")
        return self._process(path, mode="remove")

    def detect(self, path) -> bool:
        """Detect header in the file at 'path'.

        Args:
            path: File to remove header from.

        Returns:
            True if there was a header, else False
        """
        _log.debug(f"Detect header in file: {path}")
        return self._process(path, mode="detect")

    def _write_header(self, outfile):
        outfile.write(self.LINESEP.join(self._lines) + ("", self.LINESEP)[self._trail])

    @property
    def header_lines(self):
        """Return header lines as a list with '\n' separating each line."""
        if self._trail:
            return [s + self.LINESEP for s in self._lines]
        else:
            return [s + self.LINESEP for s in self._lines[:-1]] + [self._lines[-1]]


class ObservedSubject:
    event_file = "file"
    event_file_detect = "detect-file"
    event_line = "line"

    def __init__(self):
        self._obs = {}

    def add_observer(self, func, names):
        self._obs[func] = names

    def event(self, name, **kwargs):
        for obs, names in self._obs.items():
            if name in names:
                obs(name, **kwargs)


class ProgressBar:
    def __init__(self):
        self.files = []
        self.markers = ""
        self.t0, t1 = 0, 0
        self.maxlen = 0
    def begin(self):
        self.t0 = time.time()
        print(f"{'Process':20s} [", end="\r")

    def end(self):
        self.t1 = time.time()
        sec = self.t1 - self.t0
        p = f"processed {len(self.files)} files in {sec:.3f} seconds"
        if len(p) < self.maxlen:
            p += " " * (self.maxlen - len(p))
        print(p)

    def file_processed(self, event, path=None, written=True, **kwargs):
        self.files.append(path)
        self.markers += "." if written else " "
        name = path.name[:20]
        n = len(self.files)
        p = f"({n:<4d}) {name:20s} [{self.markers}]"
        print(p, end="\r")
        self.maxlen = max(self.maxlen, len(p))
        # time.sleep(0.5) # for debugging


class TextFileModifier(FileModifier, ObservedSubject):
    """Modify a file with a header."""

    # File 'magic' allowed in first two header_lines before comment
    magic_expr = re.compile(
        r"^[ \t\f]*#" "(.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+|" "!/.*)"
    )

    def __init__(self, text: str = None, **kwargs):
        """Constructor.

        Args:
            text: Text to place in header. Ignore for remove and detect functions.
            kwargs: See superclass
        """
        ObservedSubject.__init__(self)
        FileModifier.__init__(self, text, add_trailing_linesep=True, **kwargs)

    def _process(self, path: Path, mode) -> bool:
        # move input file to <name>.orig
        orig_mode = path.stat().st_mode
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
        non_whitespace = 0
        try:
            header_written = False
            # Main loop
            for line in f:
                self.event(ObservedSubject.event_line, path=path, index=lineno)
                line_stripped = line.strip()
                non_whitespace += len(line_stripped)
                if state == "pre":
                    if line_stripped.startswith(self._minsep):  # start of header
                        state = "header"
                    elif lineno < 3 and self.magic_expr.match(line_stripped):
                        if mode != "detect":
                            out.write(line)
                    else:
                        if non_whitespace > 0 or self._empty:
                            state = "post"  # no header, will copy rest of file
                        elif line and out:
                            out.write(line)
                    # if we changed state, write the header (or skip it)
                    if state != "pre" and mode == "replace":
                        self._write_header(out)
                        header_written = True
                    if state == "post" and mode != "detect":
                        # no header, so write last line of text below header
                        out.write(line)
                elif state == "header":
                    # none of the modes write the old header
                    if line_stripped.startswith(self._minsep):  # end of header
                        detected = True
                        state = "post"
                elif state == "post":
                    # replace/remove both copy all header_lines after header
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
        elif state == "pre":
            # Write header in empty or file-magic-only files
            if non_whitespace > 0 or self._empty:
                if lineno > 0 and line[-1] not in ("\r", "\n"):
                    out.write("\n")
                self._write_header(out)
        if mode != "detect":
            # finalize the output
            out.close()
            path.chmod(orig_mode)  # restore original mode bits
            f.close()
            # remove moved <name>.orig, the original input file
            os.unlink(wfname)
            self.event(ObservedSubject.event_file, path=path, written=header_written)
        return detected


class JupyterFileModifier(FileModifier):
    """Modify a Jupyter notebook with a header."""

    DEFAULT_HEADER_TAG = "header"
    CELL_TYPE = "code"  # "markdown"
    HIDE_TAG = "hide-cell"
    DEFAULT_VER = 4

    def __init__(self, text: str, ver: int = DEFAULT_VER, **kwargs):
        """Constructor.

        Args:
            text: Text to place in header. Ignore for remove and detect functions.
            kwargs: See superclass
        """
        super().__init__(text, add_trailing_linesep=False, **kwargs)
        self._hdr_tag = self.DEFAULT_HEADER_TAG
        self._ver = ver

    def _process(self, path: Path, mode) -> bool:
        # read in notebook
        try:
            with path.open(mode="r", encoding="utf-8") as f:
                nb = nbformat.read(f, as_version=self._ver)
            cells = nb.cells
        except json.JSONDecodeError as err:
            _log.error(f"while parsing Jupyter notebook '{path}': {err}")
            return False

        if len(cells) == 0:
            _log.error(f"Jupyter notebook is empty")
            return False

        # find header cell
        found_cell, found_index = None, -1
        for i, c in enumerate(cells):
            if (
                c.get("cell_type", "") == self.CELL_TYPE
                and "source" in c
                and self._hdr_tag in c.get("metadata", {}).get("tags", [])
            ):
                found_cell, found_index = c, i
                break

        if found_cell:
            if mode == "detect":
                return True  # nothing more to do
            elif mode == "replace":
                # Replace text in cell (and fix up tags if needed)
                found_cell["source"] = self.header_lines
                tags = found_cell["metadata"]["tags"]
                if self.HIDE_TAG not in tags:
                    tags.append(self.HIDE_TAG)
            else:  # remove
                del nb["cells"][found_index]
        else:
            if mode == "detect":
                return False
            elif mode == "replace":
                # Put new cell at top
                new_cell = getattr(nbformat, f"v{self._ver}").new_code_cell
                cell = new_cell(
                    self.header_lines, metadata={"tags": [self._hdr_tag, self.HIDE_TAG]}
                )
                nb["cells"].insert(0, cell)
            else:
                # no cell present, so nothing to do for detect/remove
                return False

        # write back new notebook
        with path.open(mode="w", encoding="utf-8") as f:
            nbformat.write(nb, f, version=nbformat.NO_CONVERT)

        return bool(found_cell)


# CLI usage

g_quiet = False


def tell_user(message):
    if not g_quiet:
        print(message)


_file_count = 0


def print_file(name):
    global _file_count
    if _file_count == 0:
        print("Files:")
    _file_count += 1
    print(f"{_file_count:3d} {name}")


def main() -> int:
    global g_quiet
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("root", help="Root path from which to find files", nargs="?")
    p.add_argument(
        "--version", help="Print current version and stop", action="store_true"
    )
    p.add_argument(
        "-c", "--config", help=f"Configuration file (default={DEFAULT_CONF})"
    )
    p.add_argument(
        "-C",
        "--comment",
        help=f"Comment prefix (default='{TextFileModifier.DEFAULT_COMMENT})'",
    )
    if nbformat is not None:
        p.add_argument(
            "-j",
            "--jupyter",
            action="store",
            metavar="SUFFIX",
            nargs="?",
            default=None,
            const=".ipynb",
            help="Also add/replace headers on Jupyter notebooks. The optional argument "
            "is the filename suffix to use in place of '.ipynb' for recognizing notebooks",
        )
        p.add_argument(
            "--notebook-version",
            action="store",
            default=JupyterFileModifier.DEFAULT_VER,
            type=int,
            help=f"Set Jupyter notebook format version "
            f"(default={JupyterFileModifier.DEFAULT_VER})",
        )
    p.add_argument(
        "-e",
        "--empty",
        action="store_true",
        help="Add headers to 'empty' files, which includes files containing only whitespace",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry",
        help="Do not modify files, just show which files would be affected",
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
        "-P",
        "--path-exclude",
        action="append",
        default=[],
        help="UNIX glob-style pattern of paths to exclude (repeatable)",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress all output")
    p.add_argument(
        "-r",
        "--remove",
        action="store_true",
        dest="remove",
        help="Remove headers from files, but do not replace them with anything",
    )
    p.add_argument(
        "--sep",
        help=f"Separator character (default='{TextFileModifier.DEFAULT_DELIM_CHAR})'",
    )
    p.add_argument(
        "--sep-len",
        type=int,
        default=-1,
        help=f"Separator length (default={TextFileModifier.DEFAULT_DELIM_LEN})",
    )
    p.add_argument(
        "-t",
        "--text",
        help="File containing header text. "
        "Ignored if --dry-run or --remove options are given.",
        "--no-progress", action="store_true", help="Do not show progress bar"
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

    if args.version:
        print(version("addheader"))
        return 0

    # Merge get initial conf from config file
    config_file = None
    if args.config:
        config_file = Path(args.config)
    else:
        try_config = Path(DEFAULT_CONF)
        try:
            try_config.open()
            config_file = try_config
        except:
            pass
    if config_file:
        if not config_file.exists():
            p.error(f"Configuration file '{args.config}' not found")
        try:
            with config_file.open() as f:
                config_data = yaml.load(f, Loader=Loader)
        except IOError as err:
            p.error(
                f"Cannot open configuration file '{config_file.name}' for reading: {err}"
            )
        except yaml.YAMLError as err:
            p.error(f"Syntax error in configuration file '{config_file.name}': {err}")
    else:
        config_data = {}

    # Set up logging from verbosity argument
    vb = 0
    if args.vb > 0:
        vb = args.vb
    elif "verbose" in config_data:
        try:
            vb = int(config_data["verbose"])
        except ValueError:
            p.error(
                f"Invalid value for verbose = '{config_data['verbose']}' "
                f"in configuration file '{config_file.name}'"
            )
    if config_data.get("quiet", None) or args.quiet:
        _log.setLevel(logging.FATAL)
        g_quiet = True
    elif vb > 1:
        _log.setLevel(logging.DEBUG)
    elif vb > 0:
        _log.setLevel(logging.INFO)
    else:
        _log.setLevel(logging.WARN)

    # progress bar
    show_progress = not (config_data.get("no-progress", None) or args.no_progress)

    # read notice from file
    notice_text = ""
    if args.text:
        text_file = args.text
    elif "text" in config_data:
        text_file = config_data["text"]
    else:
        text_file = None
    if args.remove:
        if text_file is not None:
            _log.info(f"-r/--remove option given so text '{text_file}' will be ignored")
    elif args.dry:
        if text_file is not None:
            _log.info(
                f"-n/--dry-run option given so text '{text_file}' will be ignored"
            )
    else:
        if text_file is None:
            p.error(f"-t/--text is required to replace current header text")
        try:
            with open(text_file, "r") as f:
                notice_text = f.read()
        except Exception as err:
            p.error(f"Cannot read text file: {args.text}: {err}")

    # Check input patterns
    if len(args.pattern) == 0:
        if "pattern" in config_data:
            patterns = config_data["pattern"]
        elif "patterns" in config_data:  # tolerate this alias
            patterns = config_data["patterns"]
        else:
            patterns = ["*.py", "~__init__.py"]
    else:
        patterns = args.pattern
    # sanity-check the input patterns
    for pat in patterns:
        if os.path.sep in pat:
            p.error('bad pattern "{}": must be a filename, not a path'.format(pat))

    # Jupyter
    jupyter_ext, nb_ver = None, None
    if nbformat is not None:
        if args.jupyter is None:
            if "jupyter" in config_data:
                ext = config_data["jupyter"]
                if ext is True:
                    jupyter_ext = ".ipynb"
                elif ext is False:
                    pass  # explicitly disabled
                else:
                    jupyter_ext = str(ext)
        else:
            jupyter_ext = args.jupyter
        if jupyter_ext:
            _log.debug(f"Jupyter notebooks will be processed, suffix={jupyter_ext}")
            if args.notebook_version is not None:
                nb_ver = args.notebook_version
            elif "notebook_version" in config_data:
                try:
                    nb_ver = int(config_data["jupyter_ver"])
                    if nb_ver < 1 or nb_ver > 4:
                        raise ValueError("must be between 1 and 4")
                except ValueError as err:
                    p.error(f"Bad Jupyter notebook version: {err}")
        else:
            _log.debug(f"Jupyter notebooks will not be processed")

    # Root
    if args.root:
        root_dir = args.root
    elif "root" in config_data:
        root_dir = config_data["root"]
    else:
        p.error("Root directory not found on command-line or configuration file")

    if config_data.get("path_exclude", None) is None:
        path_exclude = None if len(args.path_exclude) == 0 else args.path_exclude
    else:
        path_exclude = config_data["path_exclude"]

    # Initialize file-finder
    try:
        finder = FileFinder(
            root_dir,
            glob_patterns=patterns,
            path_exclude=path_exclude,
            jupyter_ext=jupyter_ext,
        )
    except Exception as err:
        p.error(f"Finding files: {err}")
    if len(finder) == 0:
        _log.warning(
            'No files found from "{}" matching {}'.format(root_dir, "|".join(patterns))
        )
        return 1

    # Skip whitespace
    else:
        empty_files = False

    # Find and replace files
    if args.dry:
        visit_files(finder.files, print_file)
        visit_files(finder.notebooks, print_file)
    else:
        kwargs = {}
        if args.comment:
            kwargs["comment_prefix"] = args.comment
        elif "comment" in config_data:
            kwargs["comment_prefix"] = config_data["comment"]
        if args.sep:
            kwargs["delim_char"] = args.sep[0]
        elif "sep" in config_data:
            kwargs["delim_char"] = config_data["sep"]
        if args.empty:
            kwargs["empty_files"] = args.empty
        elif "empty" in config_data:
            kwargs["empty_files"] = config_data["empty"]
        sep_len = None
        if args.sep_len > 0:
            sep_len = args.sep_len
        elif "sep-len" in config_data:
            try:
                sep_len = int(config_data["sep-len"])
            except ValueError:
                p.error(
                    f"Bad value for 'sep-len', expected number got: {config_data['sep-len']}"
                )
        if sep_len is not None:
            if sep_len < TextFileModifier.DELIM_MINLEN:
                p.error(
                    f"Separator length from '--sep-len' option must be >= {TextFileModifier.DELIM_MINLEN}"
                )
            kwargs["delim_len"] = sep_len
        modifier = TextFileModifier(notice_text, **kwargs)
        modifier_func = modifier.remove if args.remove else modifier.replace
        if show_progress:
            prog_bar = ProgressBar()
            modifier.add_observer(prog_bar.file_processed, (ObservedSubject.event_file,))
            prog_bar.begin()
        else:
            prog_bar = None
        file_list = visit_files(finder.files, modifier_func)
        if prog_bar:
            prog_bar.end()
        plural = "s" if len(file_list) > 1 else ""
        if not show_progress:
            tell_user(f"Modified {len(file_list)} source file{plural}")
        if _log.isEnabledFor(logging.DEBUG):
            tell_user(f"Files: {', '.join(map(str, file_list))}")
        # Jupyter
        if jupyter_ext:
            modifier = JupyterFileModifier(notice_text, ver=nb_ver)
            modifier_func = modifier.remove if args.remove else modifier.replace
            file_list = visit_files(finder.notebooks, modifier_func)
            if file_list:
                plural = "s" if len(file_list) > 1 else ""
                tell_user(f"Modified {len(file_list)} Jupyter notebook{plural}")
                if _log.isEnabledFor(logging.INFO):
                    tell_user(f"Notebooks: {', '.join(map(str, file_list))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
