#!/usr/bin/env -S python3 -u
"""
Grep reducer.

Input: <1><tab><line>
Output: List of <line>
"""

import sys

PAIR_LENGTH = 2


def main():
    """Perform reducing."""
    # Loop over every line in standard in
    for raw_line in sys.stdin:
        # Strip all extra white space and split by the tab
        line = raw_line.strip()
        sep = line.split("\t")

        # Skip if empty newline (length must be 2 for the pair)
        if len(sep) != PAIR_LENGTH:
            continue

        # Read (key, value) from current line
        value = sep[1]

        # Just print the value because this line has our query
        print(value)


if __name__ == "__main__":
    main()
