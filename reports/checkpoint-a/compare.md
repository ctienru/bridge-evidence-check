## case-01 (run 8)

Facts: 4 of 31 matched, 0 matched but excluded, 23 wrong value, 4 missed, 2 false positive(s); expected-absent 10 correct, 1 false positive(s). Conditions 16/20, claims 6/9.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | inconsistent_values | supported | inconsistent_values | yes |  |
| `bmi_path_a` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_c.prediabetes` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.mi` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.stroke` | not_supported | – | not_supported | – | yes |  |
| `bmi_path_c.pad` | insufficient | – | insufficient | – | yes |  |
| `exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `exclusion.osa` | insufficient | – | insufficient | – | yes |  |
| `exclusion.mash` | insufficient | – | insufficient | – | yes |  |
| `exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `patient_identity` | review | id_missing | review | id_missing | yes |  |
| `lifestyle.nutrition` | insufficient | – | review | – | no | extraction_wrong_value |
| `lifestyle.activity` | insufficient | – | insufficient | – | yes |  |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_bracket` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.exclusion.t2dm` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_c.stroke` | supported | – | supported | – | yes |  |
| `claim.exclusion.part_d_glp1` | insufficient | – | insufficient | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | review | – | no | extraction_wrong_value |
| `claim.lifestyle.activity` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[100:117] 38985609` | patient_identity | wrong_value | `D0-pa-form-draft[100:117] 38985609` | claim_document |
| `D0-pa-form-draft[118:133] 670eaf61` | patient_identity | wrong_value | `D0-pa-form-draft[118:133] 670eaf61` | claim_document |
| `D0-pa-form-draft[228:255] 5e283b8a` | pa_form_claims/claim.age_18 | wrong_value | `D0-pa-form-draft[228:255] 5e283b8a` | event_date |
| `D0-pa-form-draft[256:278] 144dde34` | pa_form_claims/claim.drug | wrong_value | `D0-pa-form-draft[256:278] 144dde34` | event_date |
| `D0-pa-form-draft[279:336] 9b2dbad4` | pa_form_claims/claim.bmi_bracket | wrong_value | `D0-pa-form-draft[329:336] 5e549f68` | event_date |
| `D0-pa-form-draft[337:356] 119a2ec1` | pa_form_claims/claim.exclusion.t2dm | wrong_value | `D0-pa-form-draft[337:356] 119a2ec1` | event_date |
| `D0-pa-form-draft[357:407] bd2e7df4` | pa_form_claims/claim.bmi_path_b.hfpef | wrong_value | `D0-pa-form-draft[357:407] bd2e7df4` | event_date |
| `D0-pa-form-draft[428:476] b4d1d7ce` | pa_form_claims/claim.exclusion.part_d_glp1 | wrong_value | `D0-pa-form-draft[428:476] b4d1d7ce` | event_date |
| `D0-pa-form-draft[477:524] 32001dde` | pa_form_claims/claim.lifestyle.nutrition | wrong_value | `D0-pa-form-draft[477:524] 32001dde` | event_date |
| `D0-pa-form-draft[525:555] ff3a1aa1` | pa_form_claims/claim.lifestyle.activity | wrong_value | `D0-pa-form-draft[525:555] ff3a1aa1` | event_date |
| `D0-pa-form-draft[408:427] 72356408` | pa_form_claims/claim.bmi_path_c.stroke | wrong_value | `D0-pa-form-draft[408:427] 72356408` | event_date |
| `D1-referral[55:128] 769e9d6b` | patient_identity | wrong_value | `D1-referral[55:128] 769e9d6b` | event_date |
| `D1-referral[129:151] e3ef7ba8` | patient_identity | wrong_value | `D1-referral[129:151] e3ef7ba8` | event_date |
| `D1-referral[152:207] a607a58e` | glp1_start | wrong_value | `D1-referral[152:207] a607a58e` | temporality |
| `D2-mtsamples-4985[505:636] 361081fa` | anthropometrics/bmi | wrong_value | `D2-mtsamples-4985[614:635] c12c5805` | relative_to_glp1_initiation |
| `D2-mtsamples-4985[1871:1975] 0ae7773e` | diagnoses/hypertension | missed | – | – |
| `D2-mtsamples-4985[1871:1975] 0ae7773e` | diagnoses/other | missed | – | – |
| `D2-mtsamples-4985[2026:2088] 414605e3` | diagnoses/hypertension | missed | – | – |
| `D2-mtsamples-4985[2026:2088] 414605e3` | diagnoses/other | missed | – | – |
| `D2-mtsamples-4985[731:839] d003afdc` | medications | wrong_value | `D2-mtsamples-4985[1343:1367] 25317fd5` | assertion_mismatch |
| `D2-mtsamples-4985[731:839] d003afdc` | medications | wrong_value | `D2-mtsamples-4985[1343:1367] 25317fd5` | assertion_mismatch |
| `D2-mtsamples-4985[1328:1659] f9605386` | medication_lists | wrong_value | `D2-mtsamples-4985[1328:1367] 5bd26c08` | assertion_mismatch |
| `D2-mtsamples-4985[168:503] df204d04` | lifestyle/nutrition | wrong_value | `D2-mtsamples-4985[251:358] 16595162` | end_kind |
| `D2-mtsamples-4985[4056:4144] 64c40460` | lifestyle/nutrition | wrong_value | `D2-mtsamples-4985[4061:4118] 805f44fb` | temporality |
| `D2-mtsamples-4985[505:636] 361081fa` | anthropometrics/height | wrong_value | `D2-mtsamples-4985[557:577] 7016e73c` | unparseable_value |
| `D2-mtsamples-4985[505:636] 361081fa` | anthropometrics/weight | wrong_value | `D2-mtsamples-4985[585:607] 7f86a273` | relative_to_glp1_initiation |
| `D2-mtsamples-4985[4146:4294] 7cabdf4d` | lifestyle/nutrition | wrong_value | `D2-mtsamples-4985[4146:4209] 13885c79` | temporality |
| – | doc_dates | false_positive | `D1-referral[0:10] c0bec6f0` | – |
| – | diagnoses/t2dm | false_positive | `D2-mtsamples-4985[1889:1975] f342d7e1` | – |

## case-07 (run 9)

Facts: 12 of 18 matched, 5 matched but excluded, 1 wrong value, 0 missed, 2 false positive(s); expected-absent 15 correct, 0 false positive(s). Conditions 20/20, claims 5/5.

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
| `D1-referral[423:456] aff55bad` | bp_readings | wrong_value | `D1-referral[423:456] aff55bad` | temporality |
| `D2-nutrition-note[62:73] c7666028` | patient_identity | matched_but_excluded | `D2-nutrition-note[62:73] c7666028` | wrong_patient |
| `D2-nutrition-note[74:89] 670eaf61` | patient_identity | matched_but_excluded | `D2-nutrition-note[74:89] 670eaf61` | wrong_patient |
| `D2-nutrition-note[91:238] 3f19601e` | lifestyle/nutrition | matched_but_excluded | `D2-nutrition-note[109:237] f289e291` | wrong_patient |
| – | patient_identity | false_positive | `D1-referral[34:54] aae81912` | – |
| – | doc_dates | false_positive | `D1-referral[17:33] 6f09346f` | – |

## case-07b (run 10)

Facts: 16 of 22 matched, 5 matched but excluded, 1 wrong value, 0 missed, 4 false positive(s); expected-absent 13 correct, 0 false positive(s). Conditions 20/20, claims 5/5.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
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
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | supported | – | yes |  |
| `claim.bmi_bracket` | conflict | – | conflict | – | yes |  |
| `claim.bmi_path_b.htn` | conflict | – | conflict | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[92:110] ef0c3a9e` | patient_identity | matched_but_excluded | `D0-pa-form-draft[92:110] ef0c3a9e` | claim_document |
| `D0-pa-form-draft[111:136] 47929e73` | patient_identity | matched_but_excluded | `D0-pa-form-draft[111:136] 47929e73` | claim_document |
| `D1-referral[423:456] aff55bad` | bp_readings | wrong_value | `D1-referral[423:456] aff55bad` | temporality |
| `D2-nutrition-note[62:73] c7666028` | patient_identity | matched_but_excluded | `D2-nutrition-note[62:73] c7666028` | wrong_patient |
| `D2-nutrition-note[74:89] 670eaf61` | patient_identity | matched_but_excluded | `D2-nutrition-note[74:89] 670eaf61` | wrong_patient |
| `D2-nutrition-note[91:238] 3f19601e` | lifestyle/nutrition | matched_but_excluded | `D2-nutrition-note[109:237] f289e291` | wrong_patient |
| – | patient_identity | false_positive | `D1-referral[34:54] aae81912` | – |
| – | patient_identity | false_positive | `D3-initiation-note[35:55] aae81912` | – |
| – | doc_dates | false_positive | `D1-referral[17:33] 6f09346f` | – |
| – | doc_dates | false_positive | `D3-initiation-note[12:34] 627082b5` | – |

## case-02 (run 11)

Facts: 11 of 19 matched, 2 matched but excluded, 6 wrong value, 0 missed, 6 false positive(s); expected-absent 16 correct, 0 false positive(s). Conditions 16/20, claims 2/4.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
| `bmi_path_a` | not_supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.hfpef` | supported | – | supported | – | yes |  |
| `bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
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
| `claim.drug` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_bracket` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_path_b.hfpef` | conflict | – | conflict | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[92:110] fd2cf193` | patient_identity | matched_but_excluded | `D0-pa-form-draft[92:110] fd2cf193` | claim_document |
| `D0-pa-form-draft[111:136] 6a3cbaad` | patient_identity | matched_but_excluded | `D0-pa-form-draft[111:136] 6a3cbaad` | claim_document |
| `D1-referral[118:167] 309626bd` | glp1_start | wrong_value | `D1-referral[118:167] 309626bd` | temporality |
| `D2-initiation-note[102:134] 5abae078` | anthropometrics/height | wrong_value | `D2-initiation-note[102:134] 5abae078` | relative_to_glp1_initiation |
| `D2-initiation-note[135:168] f504831a` | anthropometrics/weight | wrong_value | `D2-initiation-note[135:168] f504831a` | relative_to_glp1_initiation |
| `D3-pharmacy-history[109:164] b1de0426` | prior_glp1 | wrong_value | `D3-pharmacy-history[109:164] b1de0426` | temporality |
| `D3-pharmacy-history[165:220] 944f09af` | prior_glp1 | wrong_value | `D3-pharmacy-history[165:220] 944f09af` | temporality |
| `D3-pharmacy-history[221:276] 1eb49fd6` | prior_glp1 | wrong_value | `D3-pharmacy-history[221:276] 1eb49fd6` | temporality |
| – | patient_identity | false_positive | `D1-referral[34:54] 05c6b41a` | – |
| – | patient_identity | false_positive | `D2-initiation-note[35:55] 05c6b41a` | – |
| – | patient_identity | false_positive | `D3-pharmacy-history[42:62] 05c6b41a` | – |
| – | doc_dates | false_positive | `D1-referral[17:33] 6f09346f` | – |
| – | doc_dates | false_positive | `D2-initiation-note[12:34] 4503e547` | – |
| – | doc_dates | false_positive | `D3-pharmacy-history[18:41] be301064` | – |

## case-04 (run 12)

Facts: 13 of 29 matched, 2 matched but excluded, 14 wrong value, 0 missed, 6 false positive(s); expected-absent 12 correct, 0 false positive(s). Conditions 13/20, claims 2/4.

| Row | Gold | Gold flags | Live | Live flags | Match | First error |
|---|---|---|---|---|---|---|
| `age_18` | supported | – | supported | – | yes |  |
| `bmi_path_a` | not_supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_b.htn` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_b.ckd` | insufficient | – | insufficient | – | yes |  |
| `bmi_path_c` | supported | – | insufficient | – | no | extraction_wrong_value |
| `bmi_path_c.bmi` | supported | – | insufficient | – | no | extraction_wrong_value |
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
| `lifestyle.activity` | review | – | not_supported | – | no | compute_timepoint |
| `claim.age_18` | supported | – | supported | – | yes |  |
| `claim.drug` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_bracket` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.exclusion.osa` | conflict | – | conflict | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[64:82] 01b945aa` | patient_identity | matched_but_excluded | `D0-pa-form-draft[64:82] 01b945aa` | claim_document |
| `D0-pa-form-draft[83:98] 491a894e` | patient_identity | matched_but_excluded | `D0-pa-form-draft[83:98] 491a894e` | claim_document |
| `D1-referral[90:139] a905e6d2` | glp1_start | wrong_value | `D1-referral[90:139] a905e6d2` | temporality |
| `D2-clinical-timeline[92:125] 15298afc` | anthropometrics/bmi | wrong_value | `D2-clinical-timeline[92:124] 069fcbf1` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[126:159] 9223e0b6` | bp_readings | wrong_value | `D2-clinical-timeline[126:158] 3df756a7` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[161:194] f8ae0ad3` | anthropometrics/bmi | wrong_value | `D2-clinical-timeline[161:193] 2ebaa3fc` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[195:228] 4a63039d` | bp_readings | wrong_value | `D2-clinical-timeline[195:227] 9344120e` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[230:262] 3c95283b` | anthropometrics/height | wrong_value | `D2-clinical-timeline[230:261] 971646cc` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[263:296] 089fb5d6` | anthropometrics/weight | wrong_value | `D2-clinical-timeline[263:295] 281ce3a5` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[297:330] ea803f51` | bp_readings | wrong_value | `D2-clinical-timeline[297:329] 75f57118` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[380:413] fa66043a` | anthropometrics/bmi | wrong_value | `D2-clinical-timeline[380:412] 7e41af95` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[414:447] c412cf73` | bp_readings | wrong_value | `D2-clinical-timeline[414:446] cb237f6b` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[494:527] df6cad96` | anthropometrics/bmi | wrong_value | `D2-clinical-timeline[494:526] f90099a6` | relative_to_glp1_initiation, temporality |
| `D2-clinical-timeline[528:561] 6964fbd7` | bp_readings | wrong_value | `D2-clinical-timeline[528:560] df18d3b4` | relative_to_glp1_initiation, temporality |
| `D3-antihypertensive-history[110:198] 1d20c20f` | medications | wrong_value | `D3-antihypertensive-history[110:198] 1d20c20f` | event_date |
| `D3-antihypertensive-history[199:300] 275155b4` | medications | wrong_value | `D3-antihypertensive-history[199:300] 275155b4` | event_date |
| – | patient_identity | false_positive | `D1-referral[33:53] 629e31aa` | – |
| – | patient_identity | false_positive | `D2-clinical-timeline[35:55] 629e31aa` | – |
| – | patient_identity | false_positive | `D3-antihypertensive-history[53:73] 629e31aa` | – |
| – | doc_dates | false_positive | `D1-referral[16:32] 6f09346f` | – |
| – | doc_dates | false_positive | `D2-clinical-timeline[18:34] 6f09346f` | – |
| – | doc_dates | false_positive | `D3-antihypertensive-history[36:52] c9aff7a0` | – |

## case-03 (run 13)

Facts: 14 of 23 matched, 2 matched but excluded, 7 wrong value, 0 missed, 3 false positive(s); expected-absent 14 correct, 0 false positive(s). Conditions 17/20, claims 3/6.

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
| `claim.drug` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_bracket` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_path_b.htn` | review | – | insufficient | – | no | extraction_wrong_value |
| `claim.exclusion.osa` | review | – | review | – | yes |  |
| `claim.lifestyle.nutrition` | insufficient | – | insufficient | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[65:83] 6311f629` | patient_identity | matched_but_excluded | `D0-pa-form-draft[65:83] 6311f629` | claim_document |
| `D0-pa-form-draft[84:99] 972269ad` | patient_identity | matched_but_excluded | `D0-pa-form-draft[84:99] 972269ad` | claim_document |
| `D1-referral[110:165] c0ba91e2` | glp1_start | wrong_value | `D1-referral[110:165] c0ba91e2` | temporality |
| `D2-mtsamples-4689[92:103] c2b516ec` | patient_identity | wrong_value | `D2-mtsamples-4689[92:103] c2b516ec` | assertion_mismatch |
| `D2-mtsamples-4689[893:923] 70915489` | diagnoses/hypertension | wrong_value | `D2-mtsamples-4689[141:190] 615d86fd` | assertion_mismatch |
| `D2-mtsamples-4689[1511:1522] 36206672` | bp_readings | wrong_value | `D2-mtsamples-4689[1511:1522] 36206672` | relative_to_glp1_initiation |
| `D2-mtsamples-4689[1564:1569] 7a22ad88` | anthropometrics/height | wrong_value | `D2-mtsamples-4689[1559:1569] 78ebeb37` | unparseable_value |
| `D2-mtsamples-4689[1577:1583] f31e5624` | anthropometrics/weight | wrong_value | `D2-mtsamples-4689[1572:1583] a644c23e` | relative_to_glp1_initiation |
| `D2-mtsamples-4689[2007:2023] 3e935a1c` | diagnoses/hypertension | wrong_value | `D2-mtsamples-4689[141:190] 615d86fd` | assertion_mismatch |
| – | patient_identity | false_positive | `D1-referral[33:54] d93c2cc1` | – |
| – | medications | false_positive | `D2-mtsamples-4689[844:850] c8754abc` | – |
| – | medications | false_positive | `D2-mtsamples-4689[866:872] 3e67ff66` | – |

## case-17 (run 14)

Facts: 10 of 16 matched, 3 matched but excluded, 3 wrong value, 0 missed, 4 false positive(s); expected-absent 18 correct, 0 false positive(s). Conditions 20/20, claims 5/6.

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
| `claim.drug` | supported | – | insufficient | – | no | extraction_wrong_value |
| `claim.bmi_bracket` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.htn` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_b.hfpef` | insufficient | – | insufficient | – | yes |  |
| `claim.bmi_path_c.mi` | supported | – | supported | – | yes |  |

| Gold fact | Field | Outcome | Evidence | Reasons / keys |
|---|---|---|---|---|
| `D0-pa-form-draft[67:85] 0bcd888e` | patient_identity | matched_but_excluded | `D0-pa-form-draft[67:85] 0bcd888e` | claim_document |
| `D0-pa-form-draft[86:101] e9a030ab` | patient_identity | matched_but_excluded | `D0-pa-form-draft[86:101] e9a030ab` | claim_document |
| `D1-referral[105:160] 6059e87a` | glp1_start | wrong_value | `D1-referral[105:160] 6059e87a` | temporality |
| `D1-referral[161:253] 41bc5300` | doc_dates | matched_but_excluded | `D1-referral[161:253] 41bc5300` | value_not_in_quote |
| `D2-case-report-cureus-2025[8:366] 0ab016c2` | patient_identity | wrong_value | `D2-case-report-cureus-2025[8:26] 3f432e74` | event_date |
| `D2-case-report-cureus-2025[507:661] ef337a7f` | bp_readings | wrong_value | `D2-case-report-cureus-2025[554:583] 0e8dedf5` | event_date, relative_to_glp1_initiation |
| – | patient_identity | false_positive | `D1-referral[33:49] 25ef92a1` | – |
| – | doc_dates | false_positive | `D1-referral[16:32] 6f09346f` | – |
| – | medications | false_positive | `D2-case-report-cureus-2025[2143:2164] ac0b0d53` | – |
| – | medications | false_positive | `D2-case-report-cureus-2025[2169:2207] 7763a3e0` | – |
