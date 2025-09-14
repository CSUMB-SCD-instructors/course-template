# Autograding

This repository is intended to be set up to work cleanly with the [autograder](https://github.com/OtterDen-Lab/Autograder).  
My goal is to make it so that as long as you have a script, [grader.py](grader.py) that can grade your assignments then it can be tied in to the Autograder with minimal setup.

## What is needed

Essentially, make it so that when we type in `python scripts/grader.py --PA PA1` it will output a file located at `/tmp/feedback.yaml` that can be then read in.
This will mean updating the `grade` function.
Right now it is set up as a default function, shown below.


```python
def grade(*args, **kwargs) -> GradingResult:
  # todo: Replace this code with whatever you need to do to grade an assignment!
  
  default_results = GradingResult(
    100.0,
    comments="No grading done.",
    logs="N/A"
  )
  
  return default_results
```

The grader will expect, at a minimum, three fields:
1. `grade` (required)
2. `comments` (optional, but strongly recommended)
3. `logs` (optional, but strongly recommended)

I will try to make it possible to support more keys and arbitrary formatting on the grader side (stay tuned for updates), but no promises yet on a timeline.

## Other things you can do

If you need other flags, I will try to make it possible to pass these in as well -- it shouldn't be too difficult but as with the formatting I make no promises on timeline as my grader works well enough right now.

## Formatting

Note that not all unit tests do a great job formatting their output -- I had to make a bridge script to fix json output.  
This is why I strongly recommend using `pyyaml` as your output approach whenever possible.  
Strictly speaking I think that json would work, too, but am personally moving away from it. 