## case-01 (run 22)

Facts: 9 of 31 matched, 0 matched but excluded, 18 wrong value, 4 missed, 1 false positive(s); expected-absent 11 correct, 0 false positive(s). Conditions 15/20, claims 8/9.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | inconsistent_values | supported | inconsistent_values | yes |  |
| `bmi_path_a` | supported | – | review | timing_disagreement | no | extraction_wrong_value |
| `bmi_path_b` | insufficient | – | review | – | no | extraction_wrong_value |
| `bmi_path_b.bmi` | supported | – | review | timing_disagreement | no | extraction_wrong_value |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | review | – | no | extraction_wrong_value |
| `bmi_path_c.bmi` | supported | – | review | timing_disagreement | no | extraction_wrong_value |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | not_supported | – | not_supported | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | review | id_missing | review | id_missing | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | supported | – | review | timing_disagreement | no | extraction_wrong_value |
| `claim.exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_c.stroke` | supported | – | supported | – | yes |  |
| `claim.exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `claim.lifestyle.activity` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[100:117] 38985609` | patient_identity | wrong_value | `D0-pa-form-draft[100:117] 38985609` | claim_document |
| `D0-pa-form-draft[118:133] 670eaf61` | patient_identity | wrong_value | `D0-pa-form-draft[118:133] 670eaf61` | claim_document |
| `D0-pa-form-draft[228:255] 5e283b8a` | pa_form_claims/claim.age_18 | wrong_value | `D0-pa-form-draft[228:255] 5e283b8a` | event_date |
| `D0-pa-form-draft[256:278] 144dde34` | pa_form_claims/claim.drug | wrong_value | `D0-pa-form-draft[256:278] 144dde34` | event_date |
| `D0-pa-form-draft[279:336] 9b2dbad4` | pa_form_claims/claim.bmi_bracket | wrong_value | `D0-pa-form-draft[279:336] 9b2dbad4` | event_date |
| `D0-pa-form-draft[337:356] 119a2ec1` | pa_form_claims/claim.exclusion.t2dm | wrong_value | `D0-pa-form-draft[337:356] 119a2ec1` | event_date |
| `D0-pa-form-draft[357:407] bd2e7df4` | pa_form_claims/claim.bmi_path_b.hfpef | wrong_value | `D0-pa-form-draft[357:407] bd2e7df4` | event_date |
| `D0-pa-form-draft[428:476] b4d1d7ce` | pa_form_claims/claim.exclusion.part_d_glp1 | wrong_value | `D0-pa-form-draft[428:476] b4d1d7ce` | event_date |
| `D0-pa-form-draft[477:524] 32001dde` | pa_form_claims/claim.lifestyle.nutrition | wrong_value | `D0-pa-form-draft[477:524] 32001dde` | event_date |
| `D0-pa-form-draft[525:555] ff3a1aa1` | pa_form_claims/claim.lifestyle.activity | wrong_value | `D0-pa-form-draft[525:555] ff3a1aa1` | event_date |
| `D0-pa-form-draft[408:427] 72356408` | pa_form_claims/claim.bmi_path_c.stroke | wrong_value | `D0-pa-form-draft[408:427] 72356408` | event_date |
| `D1-referral[55:128] 769e9d6b` | patient_identity | wrong_value | `D1-referral[55:128] 769e9d6b` | event_date |
| `D1-referral[129:151] e3ef7ba8` | patient_identity | wrong_value | `D1-referral[129:151] e3ef7ba8` | event_date |
| `D2-mtsamples-4985[1871:1975] 0ae7773e` | diagnoses/hypertension | missed | – | – |
| `D2-mtsamples-4985[1871:1975] 0ae7773e` | diagnoses/other | missed | – | – |
| `D2-mtsamples-4985[2026:2088] 414605e3` | diagnoses/hypertension | missed | – | – |
| `D2-mtsamples-4985[2026:2088] 414605e3` | diagnoses/other | missed | – | – |
| `D2-mtsamples-4985[731:839] d003afdc` | medications | wrong_value | `D2-mtsamples-4985[1343:1367] 25317fd5` | assertion_mismatch |
| `D2-mtsamples-4985[731:839] d003afdc` | medications | wrong_value | `D2-mtsamples-4985[1343:1367] 25317fd5` | assertion_mismatch |
| `D2-mtsamples-4985[1328:1659] f9605386` | medication_lists | wrong_value | `D2-mtsamples-4985[1328:1342] 281b7114` | assertion_mismatch |
| `D2-mtsamples-4985[168:503] df204d04` | lifestyle/nutrition | wrong_value | `D2-mtsamples-4985[4061:4143] 5644a3b9` | end_kind, program_type, temporality |
| `D2-mtsamples-4985[505:636] 361081fa` | anthropometrics/height | wrong_value | `D2-mtsamples-4985[557:577] 7016e73c` | unparseable_value |
| – | doc_dates | false_positive | `D1-referral[0:10] c0bec6f0` | – |

## case-02 (run 23)

Facts: 17 of 19 matched, 2 matched but excluded, 0 wrong value, 0 missed, 6 false positive(s); expected-absent 16 correct, 0 false positive(s). Conditions 16/20, claims 3/4.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
| `bmi_path_a` | not_supported | – | not_supported | – | yes |  |
| `bmi_path_b` | supported | – | review | – | no | extraction_wrong_value |
| `bmi_path_b.bmi` | supported | – | review | timing_disagreement | no | extraction_wrong_value |
| `bmi_path_b.hfpef` | supported | – | supported | – | yes |  |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | review | – | no | extraction_wrong_value |
| `bmi_path_c.bmi` | supported | – | review | timing_disagreement | no | extraction_wrong_value |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | review | – | review | – | yes |  |
| `patient_identity` | supported | – | supported | – | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | supported | – | review | timing_disagreement | no | rules |
| `claim.bmi_path_b.hfpef` | conflict | – | conflict | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[92:110] fd2cf193` | patient_identity | matched_but_excluded | `D0-pa-form-draft[92:110] fd2cf193` | claim_document |
| `D0-pa-form-draft[111:136] 6a3cbaad` | patient_identity | matched_but_excluded | `D0-pa-form-draft[111:136] 6a3cbaad` | claim_document |
| – | patient_identity | false_positive | `D1-referral[34:54] 05c6b41a` | – |
| – | patient_identity | false_positive | `D2-initiation-note[35:55] 05c6b41a` | – |
| – | patient_identity | false_positive | `D3-pharmacy-history[42:62] 05c6b41a` | – |
| – | doc_dates | false_positive | `D1-referral[17:33] 6f09346f` | – |
| – | doc_dates | false_positive | `D2-initiation-note[12:34] 4503e547` | – |
| – | doc_dates | false_positive | `D3-pharmacy-history[18:41] be301064` | – |

## case-03 (run 24)

Facts: 12 of 23 matched, 2 matched but excluded, 9 wrong value, 0 missed, 4 false positive(s); expected-absent 14 correct, 0 false positive(s). Conditions 17/20, claims 4/6.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
| `bmi_path_a` | not_supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | review | – | review | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | review | id_missing | review | id_missing | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_path_b.htn` | review | – | insufficient | – | no | extraction_wrong_value |
| `claim.exclusion.osa` | review | – | review | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[65:83] 6311f629` | patient_identity | matched_but_excluded | `D0-pa-form-draft[65:83] 6311f629` | claim_document |
| `D0-pa-form-draft[84:99] 972269ad` | patient_identity | matched_but_excluded | `D0-pa-form-draft[84:99] 972269ad` | claim_document |
| `D1-referral[166:242] 345e66ca` | doc_dates | wrong_value | `D1-referral[166:242] 345e66ca` | subject |
| `D2-mtsamples-4689[92:103] c2b516ec` | patient_identity | wrong_value | `D2-mtsamples-4689[92:103] c2b516ec` | assertion_mismatch |
| `D2-mtsamples-4689[893:923] 70915489` | diagnoses/hypertension | wrong_value | `D2-mtsamples-4689[2003:2020] d6673a1e` | subject |
| `D2-mtsamples-4689[1511:1522] 36206672` | bp_readings | wrong_value | `D2-mtsamples-4689[1511:1522] 36206672` | event_date, relative_to_glp1_initiation |
| `D2-mtsamples-4689[1564:1569] 7a22ad88` | anthropometrics/height | wrong_value | `D2-mtsamples-4689[1559:1569] 78ebeb37` | unparseable_value |
| `D2-mtsamples-4689[1577:1583] f31e5624` | anthropometrics/weight | wrong_value | `D2-mtsamples-4689[1572:1583] a644c23e` | event_date, relative_to_glp1_initiation |
| `D2-mtsamples-4689[1960:1992] 412cd548` | diagnoses/osa | wrong_value | `D2-mtsamples-4689[1960:2002] 9a69d8d1` | event_date |
| `D2-mtsamples-4689[2007:2023] 3e935a1c` | diagnoses/hypertension | wrong_value | `D2-mtsamples-4689[2003:2020] d6673a1e` | event_date |
| `D2-mtsamples-4689[2164:2186] 0cf4edcd` | lifestyle/nutrition | wrong_value | `D2-mtsamples-4689[2164:2187] f8573198` | event_date |
| – | patient_identity | false_positive | `D1-referral[33:54] d93c2cc1` | – |
| – | doc_dates | false_positive | `D1-referral[16:32] 6f09346f` | – |
| – | medications | false_positive | `D2-mtsamples-4689[844:850] c8754abc` | – |
| – | medications | false_positive | `D2-mtsamples-4689[866:872] 3e67ff66` | – |

## case-04 (run 25)

Facts: 19 of 29 matched, 0 matched but excluded, 10 wrong value, 0 missed, 3 false positive(s); expected-absent 12 correct, 0 false positive(s). Conditions 16/20, claims 3/4.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_a` | not_supported | – | not_supported | – | yes |  |
| `bmi_path_b` | supported | – | insufficient | – | no | compute_timepoint |
| `bmi_path_b.bmi` | supported | – | supported | – | yes |  |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | supported | – | insufficient | – | no | compute_timepoint |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | supported | – | supported | – | yes |  |
| `bmi_path_c.bmi` | supported | – | supported | – | yes |  |
| `bmi_path_c.prediabetes` | supported | – | supported | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | not_supported | – | not_supported | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | supported | – | supported | – | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | review | – | not_supported | – | no | rules |
| `claim.age_18` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | supported | – | supported | – | yes |  |
| `claim.exclusion.osa` | conflict | – | conflict | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[64:82] 01b945aa` | patient_identity | wrong_value | `D0-pa-form-draft[64:82] 01b945aa` | value_not_in_quote, claim_document |
| `D0-pa-form-draft[83:98] 491a894e` | patient_identity | wrong_value | `D0-pa-form-draft[64:82] 01b945aa` | value_not_in_quote, claim_document |
| `D1-referral[54:72] 01b945aa` | patient_identity | wrong_value | `D1-referral[54:72] 01b945aa` | value_not_in_quote |
| `D1-referral[73:88] 491a894e` | patient_identity | wrong_value | `D1-referral[54:72] 01b945aa` | value_not_in_quote |
| `D2-clinical-timeline[56:74] 01b945aa` | patient_identity | wrong_value | `D2-clinical-timeline[56:74] 01b945aa` | value_not_in_quote |
| `D2-clinical-timeline[75:90] 491a894e` | patient_identity | wrong_value | `D2-clinical-timeline[56:74] 01b945aa` | value_not_in_quote |
| `D3-antihypertensive-history[74:92] 01b945aa` | patient_identity | wrong_value | `D3-antihypertensive-history[74:92] 01b945aa` | value_not_in_quote |
| `D3-antihypertensive-history[93:108] 491a894e` | patient_identity | wrong_value | `D3-antihypertensive-history[74:92] 01b945aa` | value_not_in_quote |
| `D3-antihypertensive-history[110:198] 1d20c20f` | medications | wrong_value | `D3-antihypertensive-history[110:198] 1d20c20f` | event_date |
| `D3-antihypertensive-history[199:300] 275155b4` | medications | wrong_value | `D3-antihypertensive-history[199:300] 275155b4` | event_date |
| – | doc_dates | false_positive | `D1-referral[16:32] 6f09346f` | – |
| – | doc_dates | false_positive | `D2-clinical-timeline[18:34] 6f09346f` | – |
| – | doc_dates | false_positive | `D3-antihypertensive-history[36:52] c9aff7a0` | – |

## case-07 (run 26)

Facts: 13 of 18 matched, 5 matched but excluded, 0 wrong value, 0 missed, 2 false positive(s); expected-absent 15 correct, 0 false positive(s). Conditions 20/20, claims 5/5.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
| `bmi_path_a` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.bmi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | not_supported | same_note_list | not_supported | same_note_list | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.bmi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | conflict | – | conflict | – | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.htn` | conflict | – | conflict | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[92:110] ef0c3a9e` | patient_identity | matched_but_excluded | `D0-pa-form-draft[92:110] ef0c3a9e` | claim_document |
| `D0-pa-form-draft[111:136] 47929e73` | patient_identity | matched_but_excluded | `D0-pa-form-draft[111:136] 47929e73` | claim_document |
| `D2-nutrition-note[62:73] c7666028` | patient_identity | matched_but_excluded | `D2-nutrition-note[62:73] c7666028` | wrong_patient |
| `D2-nutrition-note[74:89] 670eaf61` | patient_identity | matched_but_excluded | `D2-nutrition-note[74:89] 670eaf61` | wrong_patient |
| `D2-nutrition-note[91:238] 3f19601e` | lifestyle/nutrition | matched_but_excluded | `D2-nutrition-note[109:237] f289e291` | wrong_patient |
| – | patient_identity | false_positive | `D1-referral[34:54] aae81912` | – |
| – | doc_dates | false_positive | `D1-referral[17:33] 6f09346f` | – |

## case-07b (run 27)

Facts: 13 of 22 matched, 1 matched but excluded, 8 wrong value, 0 missed, 2 false positive(s); expected-absent 13 correct, 0 false positive(s). Conditions 19/20, claims 4/5.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_a` | supported | – | supported | – | yes |  |
| `bmi_path_b` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.bmi` | supported | – | supported | – | yes |  |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | not_supported | same_note_list | not_supported | same_note_list | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.bmi` | supported | – | supported | – | yes |  |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | conflict | – | conflict | – | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | conflict | – | conflict | – | yes |  |
| `claim.bmi_path_b.htn` | conflict | – | conflict | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[92:110] ef0c3a9e` | patient_identity | wrong_value | `D0-pa-form-draft[92:110] ef0c3a9e` | value_not_in_quote, claim_document |
| `D0-pa-form-draft[111:136] 47929e73` | patient_identity | wrong_value | `D0-pa-form-draft[92:110] ef0c3a9e` | value_not_in_quote, claim_document |
| `D1-referral[55:73] ef0c3a9e` | patient_identity | wrong_value | `D1-referral[55:73] ef0c3a9e` | value_not_in_quote |
| `D1-referral[74:99] 47929e73` | patient_identity | wrong_value | `D1-referral[55:73] ef0c3a9e` | value_not_in_quote |
| `D2-nutrition-note[62:73] c7666028` | patient_identity | wrong_value | `D2-nutrition-note[62:73] c7666028` | value_not_in_quote, wrong_patient |
| `D2-nutrition-note[74:89] 670eaf61` | patient_identity | wrong_value | `D2-nutrition-note[62:73] c7666028` | value_not_in_quote, wrong_patient |
| `D2-nutrition-note[91:238] 3f19601e` | lifestyle/nutrition | matched_but_excluded | `D2-nutrition-note[109:237] f289e291` | wrong_patient |
| `D3-initiation-note[56:74] ef0c3a9e` | patient_identity | wrong_value | `D3-initiation-note[56:74] ef0c3a9e` | value_not_in_quote |
| `D3-initiation-note[75:100] 47929e73` | patient_identity | wrong_value | `D3-initiation-note[56:74] ef0c3a9e` | value_not_in_quote |
| – | doc_dates | false_positive | `D1-referral[17:33] 6f09346f` | – |
| – | doc_dates | false_positive | `D3-initiation-note[12:34] 627082b5` | – |

## case-17 (run 28)

Facts: 11 of 16 matched, 2 matched but excluded, 3 wrong value, 0 missed, 4 false positive(s); expected-absent 18 correct, 0 false positive(s). Conditions 20/20, claims 6/6.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
| `bmi_path_a` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.bmi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.bmi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | supported | – | supported | – | yes |  |
| `bmi_path_c.stroke` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | review | id_missing | review | id_missing | yes |  |
| `lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_c.mi` | supported | – | supported | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[67:85] 0bcd888e` | patient_identity | matched_but_excluded | `D0-pa-form-draft[67:85] 0bcd888e` | claim_document |
| `D0-pa-form-draft[86:101] e9a030ab` | patient_identity | matched_but_excluded | `D0-pa-form-draft[86:101] e9a030ab` | claim_document |
| `D1-referral[161:253] 41bc5300` | doc_dates | wrong_value | `D1-referral[161:253] 41bc5300` | value_not_in_quote |
| `D2-case-report-cureus-2025[8:366] 0ab016c2` | patient_identity | wrong_value | `D2-case-report-cureus-2025[8:26] 3f432e74` | event_date |
| `D2-case-report-cureus-2025[507:661] ef337a7f` | bp_readings | wrong_value | `D2-case-report-cureus-2025[554:583] 0e8dedf5` | event_date, relative_to_glp1_initiation |
| – | patient_identity | false_positive | `D1-referral[33:49] 25ef92a1` | – |
| – | doc_dates | false_positive | `D1-referral[16:32] 6f09346f` | – |
| – | medications | false_positive | `D2-case-report-cureus-2025[2143:2164] ac0b0d53` | – |
| – | medications | false_positive | `D2-case-report-cureus-2025[2169:2207] 7763a3e0` | – |
