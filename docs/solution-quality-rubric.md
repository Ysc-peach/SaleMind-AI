# Automatic Solution V2 quality rubric

The evaluation-only rubric in
`apps/sales/tests/test_solution_quality_v2.py` records version
`solution-quality-v2.1` with each result. Runtime parser and admission rules
remain authoritative; a quality score cannot grant admission.

Two architecture criteria have changed from the unversioned rubric:

| Criterion | Previous scoring | Version 2.1 scoring |
| --- | --- | --- |
| Component quantity (maximum 5 points) | 5 or more: 5; 3–4: 3; 2: 2; 1: 1; 0: 0 | 3 or more: 5; 2: 2; 1: 1; 0: 0 |
| Structural relationships (maximum 3 points) | Any component dependency: 3 | Any dependency: 1; any persisted request flow: 1; any persisted data flow: 1 |

Production Core generation permits at most four architecture components, so
the previous top quantity band was unreachable for a valid generated result.
Three and four complete components now qualify equally; there is no scoring
incentive to add a fourth component to an adequate three-component design.
Quantity is only one criterion: overview, responsibility, rationale, interface,
and relationships still account for the remaining 15 architecture points.

Dependencies do not establish request or data direction. The relationship
criterion reads the explicit `ArchitectureV2.flows` preserved by the Solution
payload round-trip, rather than inferring flows from dependencies. A legacy
persisted draft containing only dependencies receives one relationship point.

Architecture remains worth 20 points and the complete rubric 100 points. All
other weights, hard gates, the total pass threshold of 80, and the section
minima (architecture 12, implementation 9, acceptance 6) are unchanged. Proposal
ceilings, generation stages, grounding, provenance, atomicity, and deterministic
or Qwen admission rules are unchanged.

Historical scores, including the recorded 87, retain their original rubric.
Re-evaluating the same artifact under version 2.1 may shift the score because
the scoring standard changed; that shift is not evidence of improved solution
quality. Any cross-version comparison must identify both rubric versions and
separate rubric effects from changes to the solution artifact. Offline rubric
tests verify alignment and persistence visibility; they do not establish live
provider availability or improved live-generated solution quality.
