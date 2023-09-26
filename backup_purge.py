#!/usr/bin/env python3

# backup_purge: A tool for automatically thinning historic files and directories

# (c) Copyright Nicko van Someren, 2023
#
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software
# and associated documentation files (the “Software”), to deal in the Software without
# restriction, including without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
# BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import os
import argparse
import sys
import time
import glob
import logging
import dataclasses


@dataclasses.dataclass
class Item:
    age: float
    name: str


# Indexed with h, d, w, m or y
HOUR = 3600
DAY = HOUR * 24
WEEK = DAY * 7
MONTH = DAY * 30.4
YEAR = DAY * 365

_AGE_UNITS = {
    "h": HOUR,
    "d": DAY,
    "w": WEEK,
    "m": MONTH,
    "y": YEAR
}

LOGGER = logging.getLogger(__name__)


def parse_policy_value(value_str: str) -> tuple[float, bool]:
    """Parse a value from a policy string"""
    value_str = value_str.strip()

    if value_str in ['', 'oo', '∞', 'inf']:
        return 1000 * YEAR, False
    elif value_str[-1] in ["*", "x", "X"]:
        mult = float(value_str[:-1])
        return mult, True
    elif value_str[-1] == '%':
        mult = float(value_str[:-1])
        return mult / 100, True
    elif (unit_name := value_str[-1].lower()) in _AGE_UNITS:
        val = _AGE_UNITS[unit_name] * (1 if len(value_str) == 1 else float(value_str[:-1]))
        return val, False
    else:
        return float(value_str) * DAY, False


def generate_terms(policy):
    """Generate a sequence of (max_age, interval) pairs for retention from a policy"""
    max_age, interval = None, 0
    age_mult, interval_mult = 0, 0
    parts = policy.strip().split(",")
    if not parts or not parts[0]:
        raise ValueError("Empty policy")

    for part in parts:
        prev_age, prev_interval = max_age, interval
        if age_mult:
            raise ValueError("Age multipliers must only be used in the last policy part")

        age_str, *tail = part.split(":")

        max_age, mult_a = parse_policy_value(age_str)
        if mult_a:
            if max_age <= 1:
                raise ValueError("Age multipliers must be greater than 1")
            age_mult = max_age
            max_age *= prev_age if prev_age is not None else (3600 * 24)

        if tail:
            if len(tail) != 1:
                raise ValueError(f"Bad policy part: {part}")
            interval, mult_i = parse_policy_value(tail[0])
            if mult_i:
                if interval <= 1:
                    raise ValueError("Interval multipliers must be greater than 1")
                interval_mult = interval
                interval *= prev_interval
        else:
            if mult_a:
                interval = prev_interval * age_mult if prev_interval else (3600 * 24)
            else:
                interval = prev_age if prev_age is not None else (3600 * 24)

        if prev_age is not None and max_age < prev_age:
            raise ValueError("Policy ages must be in time order")

        yield max_age, interval

    # If an age multiplier is set then we yield indefinitely
    while age_mult:
        max_age *= age_mult
        interval *= (interval_mult if interval_mult else age_mult)
        yield max_age, interval


def group_items(items, policy):
    """Given policy and a list of items, return a list of pairs of intervals and
    lists of items whose age is less than the maximum of the policy term"""

    groups = []
    next_item = 0
    current_group = []

    term_generator = generate_terms(policy)
    max_age, interval = next(term_generator)

    while next_item < len(items):
        try:
            while items[next_item].age >= max_age:
                groups.append((interval, current_group))
                current_group = []
                max_age, interval = next(term_generator)
            current_group.append(items[next_item])
            next_item += 1
        except StopIteration:
            break

    if current_group:
        groups.append((interval, current_group))

    return groups


def filter_items(items, policy, leeway="1%"):
    """Given a list of items and a policy, return a list of items to keep
    and a list of items to discard"""

    items.sort(key=lambda i: i.age)
    grouped_items = group_items(items, policy)

    leeway_value, leeway_mult = parse_policy_value(leeway)

    keep = []
    discard = []

    for interval, group in reversed(grouped_items):
        if leeway_mult:
            if leeway_value >= 1:
                raise ValueError("Leeway multipliers must be less than 1")
            interval *= 1 - leeway_value
        else:
            interval -= leeway_value

        for item in reversed(group):
            if keep and item.age + interval > keep[-1].age:
                discard.append(item)
            else:
                keep.append(item)

    return keep, discard


def find_aged_items(file_list, timestamp_function, base_timestamp=None):
    if base_timestamp is None:
        base_timestamp = time.time()

    return [
        Item(age, name)
        for name in file_list
        if (age := base_timestamp - timestamp_function(name)) > 0
    ]


_STAT_PARSERS = {
    "c": lambda name: os.stat(name).st_ctime,
    "m": lambda name: os.stat(name).st_mtime,
    "a": lambda name: os.stat(name).st_atime,
}


def make_timestamp_parser(args):
    fmt = args.time
    if fmt in _STAT_PARSERS:
        return _STAT_PARSERS[fmt]

    leaf_only = args.leaf_only
    name_trim = os.path.basename if leaf_only else lambda name: name
    return lambda name: time.mktime(time.strptime(name_trim(name), fmt))


def main():
    parser = argparse.ArgumentParser(
        prog="backup_purge",
        description="A tool for selectively removing files or directories on a schedule"
    )

    parser.add_argument(
        "-p", "--policy",
        type=str, metavar="POLICY", default="w,m,y",
        help="Policy for the files to be kept or removed (default: 'w,m,y')"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--rm", action="store_true",
        help="Remove files rather than listing files for removal"
    )
    actions.add_argument(
        "--show-kept", action="store_true",
        help="Print the files to be kept rather than the files to remove"
    )
    parser.add_argument(
        "-v", "--verbose", action="count",  dest="verbosity", default=1,
        help="Increase the detail of output messages"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_const", dest="verbosity", const=0,
        help="Suppress regular output"
    )
    parser.add_argument(
        "-Q", "--no-errs", action="store_true",
        help="Do not report errors when removal fails"
    )
    parser.add_argument(
        "-g", "--glob", action="store_true",
        help="Expand shell wild-card characters in names"
    )
    time_group = parser.add_mutually_exclusive_group()

    time_group.add_argument(
        "-c", "--ctime", action="store_const", dest="time", default="c", const="c",
        help="Use file creation time (default)"
    )
    time_group.add_argument(
        "-m", "--mtime", action="store_const", dest="time", const="m",
        help="Use file modification time"
    )
    time_group.add_argument(
        "-a", "--atime", action="store_const", dest="time", const="a",
        help="Use file access time"
    )
    time_group.add_argument(
        "-t", "--time-pattern", metavar="FORMAT",
        action="store", dest="time",
        help="Parse timestamp from file name instead of using file timestamp"
    )
    parser.add_argument(
        "-L", "--leaf-only", action="store_true",
        help="Only parse the leaf name to extract the timestamp"
    )

    parser.add_argument(
        "-l", "--leeway",
        type=str, metavar="MARGIN",
        default="1%",
        help="Leeway for measuring age of items to discard (default: 1%%)"
    )
    parser.add_argument(
        "files", metavar="NAME", nargs="+",
        help="Files or directors to consider and/or - to take names from stdin",
    )

    args = parser.parse_args()

    # Make the correct timestamp function
    timestamp_parser = make_timestamp_parser(args)

    # Find the complete list of files to scan
    file_names = args.files

    use_names = []

    if "-" in file_names:
        use_names += sys.stdin.read().splitlines()

    if args.glob:
        use_names += sum((glob.glob(name) for name in file_names if name != "-"), [])
    else:
        use_names += [name for name in file_names if name != "-"]

    if args.verbosity >= 2:
        logging.basicConfig(level=logging.DEBUG)
    elif args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    file_items = find_aged_items(use_names, timestamp_parser)
    kept_files, to_be_removed = filter_items(file_items, args.policy, args.leeway)

    # Either remove the files or print the list of files
    if args.show_kept:
        for item in kept_files:
            print(item.name)
    else:
        if args.rm:
            for item in to_be_removed:
                os.remove(item.name)
        else:
            for item in to_be_removed:
                print(item.name)


if __name__ == "__main__":
    main()
