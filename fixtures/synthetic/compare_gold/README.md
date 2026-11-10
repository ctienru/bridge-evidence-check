Synthetic gold for `tests/test_compare_gold.py`, over `fixtures/synthetic/case-smoke` and the
`valid` fake reply. It is not annotation: it is built to exercise every comparison outcome.
Deliberate differences from the fake run: `bmi_path_a` and `claim.bmi_bracket` supported
(the referral's measurements are dated after initiation by compute), `bp_readings` with a
different diastolic value, `bmi_path_c.mi` (listed as a gold question), `exclusion.osa` and
`age_18` set to `review`, and the PA-draft identity fact (excluded by verify as
`claim_document`).
