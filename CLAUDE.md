# Fix the cause, not the case

When fixing something, fix the general cause so the same kind of problem cannot
come back, not just the one instance that was reported. Ask why the case slipped
through and change the rule, check or data flow that let it through, so that
every future case of the same shape is handled too. Avoid hardcoding the
reported ticker, filing, source or value as a special case. Where the fix rests
on a threshold or heuristic, check it against real data, both the cases it
should catch and the ones it must not, and cover both with tests.
