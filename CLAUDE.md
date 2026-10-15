# Fix the cause, not the case

When fixing something, fix the general cause so the same kind of problem cannot
come back, not just the one instance that was reported. Ask why the case slipped
through and change the rule, check or data flow that let it through, so that
every future case of the same shape is handled too. Avoid hardcoding the
reported ticker, filing, source or value as a special case. Where the fix rests
on a threshold or heuristic, check it against real data, both the cases it
should catch and the ones it must not, and cover both with tests.

# Project verification

After making any implementation change anywhere in this workspace—including code, UI, configuration, schemas, scripts, workflows, or product behavior—use the project `/implementation-qa` skill before declaring the task complete.

Apply verification proportional to the change, fix in-scope failures, and retest. If a relevant check cannot be run, report the exact limitation instead of treating it as passed. Do not invoke the skill for explanation-only, research-only, or other read-only tasks with no implementation change.
