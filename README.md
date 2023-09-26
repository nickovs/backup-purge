# backup-purge

### A tool for automatically thinning historic files and directories

`backup-purge` is designed to be a simple-to-use tool for automatically removing some
but not all of a set of files based on the files' dates and a retention policy. It
offers flexibility both in terms of the retention policy and what date or time stamp 
is used to determine the age of the file. It can handle the removal of the files or 
directories themselves, or it can emit a list of either the files to remove or the files 
to keep. It can also take a list of names that do not represent files but which include
time and date information, and apply the same policies to those names based on their
embedded dates.

## Usage

If you want to use the default retention policy and simply have `backup-purge` tell you which
files or directories should be removed, based on their creation timestamp, you can just call
the program with a list of file names as the arguments:
```bash
backup-purge /path/to/backups/*
```
The output from this can be used to test the policy, or it can be fed into a tools such as
`xargs` to perform some action on the selected files. 


## Describing retention policies

A retention policy consists of a sequence of time periods representing a maximum age
and a minimum time interval between retained versions up to that age. For example a common
policy (and the default policy for `backup-purge`) is *"keep daily backups up to a week
back, weekly backups up to a month back and monthly backups up to a year back"*.

Policies for `backup-purge` are written as a comma-separated list of terms that define the
pairs that make up the policy. Each term explicitly defines the end age for the period and
may  either explicitly provide a minimum interval or derive it from the previous period.

Values in the terms are usually given as a number of units; supported units are hours, days,
weeks, months and years. Floating point values are supported for the number, and the unit is
a single letter `h`, `d`, `w`, `m` or `y`. The default unit is days, so a number on its own
specifies a number of days, while a unit on its own implicitly has a quantity of 1. For example
`168h`, `7` and `w` all specify the same one-week value.

The age limit and the minimum interval in the term are separated by a colon. If the colon is
missing then by default the target interval for this term is taken as the maximum age of the
previous term. For the first term in the policy, the previous term is taken to have a maximum
age of 1 day, so the default policy described above can be written simply as `w,m,y`, while
`1:6h,2w:48h,y:w` means *"every 6 hours for the first day, every two days for two weeks and then
weekly for a year"*.

It is possible to specify an indefinite term by giving a value of infinity (which is the same
in any unit, so a unit is not needed). Infinity can be written using the unicode `∞` character
or the ASCII `oo` or `inf`. Additionally, an empty position is also considered to be infinity.
As a result the empty policy string means *"daily, forever"*, since the empty position for the
end age is taken as infinity and the inherited frequency at the start of the policy is daily.
Similarly, the policy consisting of a single colon, `:`, means *"only keep the oldest file"*,
since the term end is infinity and so is the target interval. A zero age is not meaningful, but
a zero interval will keep all files up to the end age; it is sometimes helpful to start a
policy with the term `d:0` which means *"keep everything less than a day old"*. The policy
`∞:0` means *"keep everything forever"*, which is slightly less useful.

In addition to the above, there is also a special 'unit', written as `x` or `*`, which takes
the previous value for that part of the term as the unit. Using this unit also changes the
behaviour of the policy interpreter if it is used for the end of the last term, in that it
will then be applied repeatedly until the end age is greater than the age of the oldest file.
Furthermore, if the multiplier unit is only given for the end age *the same* multiplier will
be applied to the target interval. Thus, a policy of `3x` means *"daily up to 3 days, every 3
days up to 9 days, every 9 days up to 27 days and continue until all files are considered"*.
Multipliers must be greater than one.

## Leeway

It is often the case when taking backups or creating files on a periodic basis that the time
it takes for the files to be created varies a little. Depending on how the time stamps are
created this may mean that daily backups might end up being slightly more or slightly less
than one day apart. In order to avoid deletion of a file that should be retained simply
because it took a little less time to create then its predecessor, `backup-purge` allows
you to specify some leeway using the `--leeway` or `-L` options. The leeway value is subtracted
from the nominal interval in time period and may be expressed as an explicit duration (e.g. `1h`)
or as a multiplier or percentage of the interval in each period (e.g. `0.05x` or `5%`).
By default, 1% leeway is allowed (just under 15 minutes per day).

## Hints and tips

It is generally a good idea to run the tool before taking the next backup for two reasons.
Firstly, this reduced the risk of running out of space when taking the backup. Secondly, it
reduced the risk of your policy accidentally deleting the new backup, since if the new backup
completed slightly more quickly than last one, not enough leeway was allowed and the first
term in the policy has a target interval the same as the period between backups, the tool
might see two backups in the first period.

Some care may need to be taken in the event that the target interval does not neatly divide
the length of a term. In practice the algorithm will tend to keep more backups than you would
expect, which is the safer option.
