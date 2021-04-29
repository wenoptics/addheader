# addheader - add headers to files
This repository contains a single command to manage a header section, 
e.g. copyright, for a source code tree.

Using UNIX glob patterns, _addheader_ modifies an entire tree of
source code at once. The program replaces existing headers with
an updated version, and places the header after any shell magic
at the top of the file.

## Installation

_addheader_ is written in Python and can be simply installed from the PyPI package:

`pip install addheader`

## Usage

Use the command `addheader`. Invoking`addheader -h` shows a detailed help message
for the command arguments and options. Below are some examples and comments on usage.

### Basic usage

If you have the header file in "copyright.txt", and your source tree is a Python
package located at "./mypackage",
then you would invoke the program like this:
```shell
adddheader mypackage --text copyright.txt
```
By default, the header will not be added to "__init__.py" files.

### Specifying file patterns

You can customize the files that
are modified with the `-p` or `--pattern` argument, which takes a UNIX glob-style pattern and can be
repeated as many times as you like. To help exclude files, if the '~' is the first letter of the pattern,
then the rest of the pattern is used to exclude (not include) files. So, for example, if you provide the
following source code tree:
```
mypackage
   __init__.py
   foo.py
   bar.py
   tests/
       __init__.py
       test_foo.py
       test_bar.py
```
The following commands would match the following lists of files:

* `addheader mypackage -t header.txt -p *.py`  
mypackage/{__init__.py, foo.py, bar.py}, mypackage/tests/{__init__.py, test_foo.py, test_bar.py}
* `addheader mypackage -t header.txt -p *.py -p ~__init__.py`  
mypackage/{foo.py, bar.py}, mypackage/tests/{test_foo.py, test_bar.py}
* `addheader mypackage -t header.txt -p *.py -p ~__init__.py -p ~test_*.py`  
mypackage/{foo.py, bar.py}
  
### Header delimiters

The header itself is delimited by a line of 78 '#' characters. While _detecting_ an existing
header, the program will look for any separator of 10 or more '#' characters.
For example, if you have a file that looks like this:
```python
##########
my header with 10
hashes above and below
##########
hello
```

and a header text file containing simply "Hello, world!", then the modified
header will be:
```python
##############################################################################
# Hello, world!
##############################################################################
hello
```

### Using in tests

To test your package for files missing headers, use the following formula:
```python
import os
import mypackage
from addheader.add import FileFinder, detect_files

def test_headers():
    root = os.path.dirname(mypackage.__file__)
    # modify patterns to match the files that should have headers
    ff = FileFinder(root, glob_pat=["*.py", "~__init__.py"])
    has_header, missing_header = detect_files(ff)
    assert len(missing_header) == 0
```

## Credits
The _addheader_ program was developed for use in the [IDAES](www.idaes.org) project and is maintained in the
IDAES organization in Github at https://github.com/IDAES/addheader . The primary author
and maintainer is Dan Gunter (dkgunter at lbl dot gov).

## License
Please see the COPYRIGHT.md and LICENSE.md files in the repository for
limitations on use and distribution of this software.