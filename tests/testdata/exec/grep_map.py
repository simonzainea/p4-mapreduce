#!/usr/bin/env -S python3 -u
"""
Grep mapper.

Input: <line>
Output: <1><tab><line>
"""

import sys


def main():
    """Perform mapping."""
    # Define our query term
    query = "product" if len(sys.argv) == 1 else sys.argv[1]

    # Loop over every line in standard in
    for raw_line in sys.stdin:
        line = raw_line.strip()

        if not line:
            continue

        # Print key, value pair if query present in this line
        if query in line.lower():
            print("1\t" + line)


if __name__ == "__main__":
    main()
