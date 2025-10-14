#!env python

import dataclasses
import yaml
import argparse


@dataclasses.dataclass
class GradingResult:
  grade : float
  comments : str
  logs : str


def parse_flags():
  parser = argparse.ArgumentParser()
  
  parser.add_argument(
    "--PA", "--pa",
    required=True,
    help="Name of the PA (e.g. \"PA1\") to grade.  If it matches Canvas or your LMS it can be easier."
  )
  parser.add_argument(
    "--output-path",
    dest="output_path",
    default="/tmp/feedback.yaml",
    help="Override for where to output the feedback.yaml file."
  )
  
  return parser.parse_args()


def grade(PA, *args, **kwargs) -> GradingResult:
  # todo: Replace this code with whatever you need to do to grade an assignment!
  
  default_results = GradingResult(
    0.0,
    comments="No grading done.",
    logs="N/A"
  )
  
  return default_results

def main():
  flags = parse_flags()
  
  result = grade(**vars(flags))
  
  with open(flags.output_path, 'w') as yaml_fid:
    yaml.safe_dump(
      dataclasses.asdict(result),
      yaml_fid,
      sort_keys=False
    )
  
  
  pass


if __name__ == "__main__":
  main()
