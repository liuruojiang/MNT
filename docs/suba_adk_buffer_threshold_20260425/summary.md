# Sub-A / Sub-A-DK Buffer Threshold Scan

- Data source: production `fetch_cn_kline()` path from `mnt_bot V 7.1 plus.py`
- Window: same aligned common sample used by `analyze_suba_adk_signal_mix_compare.py`
- Costs: `CN_COMMISSION` from production script; existing Sub-A and DK overlays are applied
- Sub-A buffer: if the current holding remains eligible, a challenger must beat current averaged score by the threshold before switching
- Sub-A-DK buffer: if the current index pair remains scored, a challenger pair must beat its absolute score by the threshold before switching pair; pair direction still follows the original pair signal

## Validation
- suba_baseline_60_20_20_threshold_1p00_nav_max_abs_diff: 0
- adk_baseline_60_20_threshold_1p00_nav_max_abs_diff: 0
- adk_formal_baseline_60_20_threshold_1p00_nav_max_abs_diff: 0

## Sub-A

### baseline_60_20_20
#### last_3y
- candidate_1p02x: CAGR 36.37%, Sharpe 1.674, MaxDD -12.23%, Signals 613
- candidate_1p05x: CAGR 36.24%, Sharpe 1.670, MaxDD -13.15%, Signals 600
- candidate_1p10x: CAGR 35.93%, Sharpe 1.640, MaxDD -13.15%, Signals 597
- legacy_no_buffer_1p00x: CAGR 34.46%, Sharpe 1.603, MaxDD -12.78%, Signals 626
- candidate_1p15x: CAGR 33.38%, Sharpe 1.540, MaxDD -13.15%, Signals 599
- candidate_1p20x: CAGR 33.02%, Sharpe 1.529, MaxDD -13.15%, Signals 593
- Winner by Sharpe: candidate_1p02x
#### last_5y
- candidate_1p02x: CAGR 29.64%, Sharpe 1.453, MaxDD -15.87%, Signals 613
- candidate_1p05x: CAGR 29.13%, Sharpe 1.434, MaxDD -15.87%, Signals 600
- candidate_1p10x: CAGR 29.39%, Sharpe 1.433, MaxDD -15.76%, Signals 597
- legacy_no_buffer_1p00x: CAGR 28.51%, Sharpe 1.407, MaxDD -15.87%, Signals 626
- candidate_1p15x: CAGR 27.86%, Sharpe 1.373, MaxDD -15.76%, Signals 599
- candidate_1p20x: CAGR 27.27%, Sharpe 1.354, MaxDD -15.53%, Signals 593
- Winner by Sharpe: candidate_1p02x
#### last_10y
- candidate_1p20x: CAGR 24.18%, Sharpe 1.236, MaxDD -21.52%, Signals 593
- candidate_1p05x: CAGR 23.82%, Sharpe 1.215, MaxDD -24.36%, Signals 600
- candidate_1p15x: CAGR 23.83%, Sharpe 1.214, MaxDD -22.27%, Signals 599
- candidate_1p10x: CAGR 23.82%, Sharpe 1.212, MaxDD -25.03%, Signals 597
- legacy_no_buffer_1p00x: CAGR 23.37%, Sharpe 1.199, MaxDD -23.24%, Signals 626
- candidate_1p02x: CAGR 23.28%, Sharpe 1.194, MaxDD -24.36%, Signals 613
- Winner by Sharpe: candidate_1p20x
#### full_common
- candidate_1p15x: CAGR 30.14%, Sharpe 1.417, MaxDD -22.94%, Signals 599
- candidate_1p10x: CAGR 30.03%, Sharpe 1.415, MaxDD -25.03%, Signals 597
- candidate_1p20x: CAGR 29.83%, Sharpe 1.412, MaxDD -23.77%, Signals 593
- candidate_1p05x: CAGR 29.37%, Sharpe 1.393, MaxDD -24.36%, Signals 600
- candidate_1p02x: CAGR 28.64%, Sharpe 1.368, MaxDD -24.36%, Signals 613
- legacy_no_buffer_1p00x: CAGR 28.47%, Sharpe 1.363, MaxDD -23.24%, Signals 626
- Winner by Sharpe: candidate_1p15x

### mix_50_15__60_20__70_25
#### last_3y
- candidate_1p20x: CAGR 32.79%, Sharpe 1.525, MaxDD -14.74%, Signals 603
- candidate_1p15x: CAGR 31.68%, Sharpe 1.480, MaxDD -15.11%, Signals 603
- candidate_1p02x: CAGR 28.49%, Sharpe 1.354, MaxDD -15.58%, Signals 612
- candidate_1p10x: CAGR 28.72%, Sharpe 1.352, MaxDD -14.74%, Signals 604
- candidate_1p05x: CAGR 28.13%, Sharpe 1.336, MaxDD -17.13%, Signals 605
- legacy_no_buffer_1p00x: CAGR 27.68%, Sharpe 1.321, MaxDD -15.42%, Signals 626
- Winner by Sharpe: candidate_1p20x
#### last_5y
- candidate_1p20x: CAGR 26.37%, Sharpe 1.313, MaxDD -14.88%, Signals 603
- candidate_1p15x: CAGR 26.26%, Sharpe 1.303, MaxDD -16.85%, Signals 603
- candidate_1p10x: CAGR 24.08%, Sharpe 1.207, MaxDD -17.26%, Signals 604
- candidate_1p05x: CAGR 23.01%, Sharpe 1.169, MaxDD -17.13%, Signals 605
- candidate_1p02x: CAGR 22.47%, Sharpe 1.145, MaxDD -17.77%, Signals 612
- legacy_no_buffer_1p00x: CAGR 21.87%, Sharpe 1.120, MaxDD -17.77%, Signals 626
- Winner by Sharpe: candidate_1p20x
#### last_10y
- candidate_1p15x: CAGR 21.57%, Sharpe 1.123, MaxDD -32.57%, Signals 603
- candidate_1p20x: CAGR 21.38%, Sharpe 1.118, MaxDD -32.57%, Signals 603
- candidate_1p10x: CAGR 20.54%, Sharpe 1.076, MaxDD -31.98%, Signals 604
- candidate_1p02x: CAGR 19.84%, Sharpe 1.046, MaxDD -31.81%, Signals 612
- legacy_no_buffer_1p00x: CAGR 19.28%, Sharpe 1.020, MaxDD -31.81%, Signals 626
- candidate_1p05x: CAGR 19.17%, Sharpe 1.015, MaxDD -31.73%, Signals 605
- Winner by Sharpe: candidate_1p15x
#### full_common
- candidate_1p20x: CAGR 25.08%, Sharpe 1.234, MaxDD -32.57%, Signals 603
- candidate_1p15x: CAGR 25.07%, Sharpe 1.233, MaxDD -32.57%, Signals 603
- candidate_1p10x: CAGR 24.74%, Sharpe 1.218, MaxDD -31.98%, Signals 604
- candidate_1p05x: CAGR 23.44%, Sharpe 1.165, MaxDD -31.73%, Signals 605
- candidate_1p02x: CAGR 23.19%, Sharpe 1.157, MaxDD -31.81%, Signals 612
- legacy_no_buffer_1p00x: CAGR 22.91%, Sharpe 1.143, MaxDD -31.81%, Signals 626
- Winner by Sharpe: candidate_1p20x

### mix_55_15__60_20__80_25
#### last_3y
- candidate_1p20x: CAGR 29.63%, Sharpe 1.397, MaxDD -15.41%, Signals 581
- candidate_1p15x: CAGR 29.27%, Sharpe 1.384, MaxDD -15.41%, Signals 583
- candidate_1p05x: CAGR 29.01%, Sharpe 1.370, MaxDD -15.68%, Signals 589
- candidate_1p02x: CAGR 28.25%, Sharpe 1.343, MaxDD -15.95%, Signals 599
- legacy_no_buffer_1p00x: CAGR 28.19%, Sharpe 1.340, MaxDD -15.92%, Signals 603
- candidate_1p10x: CAGR 28.03%, Sharpe 1.333, MaxDD -17.13%, Signals 590
- Winner by Sharpe: candidate_1p20x
#### last_5y
- candidate_1p15x: CAGR 23.45%, Sharpe 1.186, MaxDD -17.13%, Signals 583
- candidate_1p20x: CAGR 23.15%, Sharpe 1.177, MaxDD -17.27%, Signals 581
- candidate_1p05x: CAGR 22.29%, Sharpe 1.136, MaxDD -16.65%, Signals 589
- candidate_1p10x: CAGR 22.23%, Sharpe 1.134, MaxDD -17.41%, Signals 590
- candidate_1p02x: CAGR 21.13%, Sharpe 1.090, MaxDD -16.12%, Signals 599
- legacy_no_buffer_1p00x: CAGR 21.10%, Sharpe 1.088, MaxDD -16.12%, Signals 603
- Winner by Sharpe: candidate_1p15x
#### last_10y
- candidate_1p15x: CAGR 20.45%, Sharpe 1.076, MaxDD -29.97%, Signals 583
- candidate_1p05x: CAGR 19.70%, Sharpe 1.038, MaxDD -31.26%, Signals 589
- candidate_1p20x: CAGR 19.50%, Sharpe 1.031, MaxDD -30.95%, Signals 581
- legacy_no_buffer_1p00x: CAGR 19.38%, Sharpe 1.027, MaxDD -28.77%, Signals 603
- candidate_1p10x: CAGR 19.27%, Sharpe 1.021, MaxDD -31.96%, Signals 590
- candidate_1p02x: CAGR 18.63%, Sharpe 0.996, MaxDD -30.84%, Signals 599
- Winner by Sharpe: candidate_1p15x
#### full_common
- candidate_1p15x: CAGR 24.47%, Sharpe 1.208, MaxDD -29.97%, Signals 583
- candidate_1p05x: CAGR 24.19%, Sharpe 1.197, MaxDD -31.26%, Signals 589
- candidate_1p10x: CAGR 23.85%, Sharpe 1.181, MaxDD -31.96%, Signals 590
- legacy_no_buffer_1p00x: CAGR 23.71%, Sharpe 1.178, MaxDD -28.77%, Signals 603
- candidate_1p20x: CAGR 23.20%, Sharpe 1.156, MaxDD -30.95%, Signals 581
- candidate_1p02x: CAGR 22.57%, Sharpe 1.131, MaxDD -30.84%, Signals 599
- Winner by Sharpe: candidate_1p15x

## Sub-A-DK

### baseline_60_20
#### last_3y
- legacy_no_buffer_1p00x: CAGR 28.90%, Sharpe 1.306, MaxDD -17.37%, Signals 623
- candidate_1p02x: CAGR 26.57%, Sharpe 1.233, MaxDD -19.12%, Signals 586
- candidate_1p05x: CAGR 25.92%, Sharpe 1.212, MaxDD -18.91%, Signals 537
- candidate_1p15x: CAGR 26.03%, Sharpe 1.211, MaxDD -22.48%, Signals 472
- candidate_1p10x: CAGR 25.42%, Sharpe 1.187, MaxDD -21.36%, Signals 494
- candidate_1p20x: CAGR 22.64%, Sharpe 1.063, MaxDD -23.35%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_5y
- legacy_no_buffer_1p00x: CAGR 32.34%, Sharpe 1.464, MaxDD -17.37%, Signals 623
- candidate_1p02x: CAGR 30.17%, Sharpe 1.397, MaxDD -19.12%, Signals 586
- candidate_1p05x: CAGR 29.65%, Sharpe 1.381, MaxDD -18.91%, Signals 537
- candidate_1p15x: CAGR 27.87%, Sharpe 1.320, MaxDD -22.48%, Signals 472
- candidate_1p10x: CAGR 26.57%, Sharpe 1.268, MaxDD -21.36%, Signals 494
- candidate_1p20x: CAGR 24.53%, Sharpe 1.176, MaxDD -23.35%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_10y
- legacy_no_buffer_1p00x: CAGR 32.12%, Sharpe 1.491, MaxDD -20.00%, Signals 623
- candidate_1p05x: CAGR 31.03%, Sharpe 1.454, MaxDD -20.20%, Signals 537
- candidate_1p02x: CAGR 30.37%, Sharpe 1.434, MaxDD -20.22%, Signals 586
- candidate_1p10x: CAGR 27.04%, Sharpe 1.304, MaxDD -21.36%, Signals 494
- candidate_1p15x: CAGR 25.25%, Sharpe 1.235, MaxDD -22.48%, Signals 472
- candidate_1p20x: CAGR 22.73%, Sharpe 1.125, MaxDD -23.35%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x
#### full_common
- legacy_no_buffer_1p00x: CAGR 27.26%, Sharpe 1.311, MaxDD -33.51%, Signals 623
- candidate_1p02x: CAGR 26.02%, Sharpe 1.266, MaxDD -33.45%, Signals 586
- candidate_1p05x: CAGR 25.37%, Sharpe 1.236, MaxDD -35.47%, Signals 537
- candidate_1p10x: CAGR 20.94%, Sharpe 1.056, MaxDD -41.96%, Signals 494
- candidate_1p15x: CAGR 20.01%, Sharpe 1.017, MaxDD -40.51%, Signals 472
- candidate_1p20x: CAGR 17.44%, Sharpe 0.907, MaxDD -44.05%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x

### mix2_60_20__65_20
#### last_3y
- legacy_no_buffer_1p00x: CAGR 28.49%, Sharpe 1.294, MaxDD -19.48%, Signals 614
- candidate_1p02x: CAGR 25.50%, Sharpe 1.186, MaxDD -20.34%, Signals 577
- candidate_1p05x: CAGR 24.35%, Sharpe 1.145, MaxDD -23.45%, Signals 550
- candidate_1p10x: CAGR 23.59%, Sharpe 1.119, MaxDD -24.05%, Signals 508
- candidate_1p15x: CAGR 20.95%, Sharpe 1.003, MaxDD -27.70%, Signals 489
- candidate_1p20x: CAGR 17.92%, Sharpe 0.883, MaxDD -26.28%, Signals 467
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_5y
- legacy_no_buffer_1p00x: CAGR 30.43%, Sharpe 1.397, MaxDD -19.48%, Signals 614
- candidate_1p02x: CAGR 30.17%, Sharpe 1.389, MaxDD -20.34%, Signals 577
- candidate_1p05x: CAGR 29.26%, Sharpe 1.355, MaxDD -23.45%, Signals 550
- candidate_1p10x: CAGR 27.11%, Sharpe 1.287, MaxDD -24.05%, Signals 508
- candidate_1p15x: CAGR 25.25%, Sharpe 1.206, MaxDD -27.70%, Signals 489
- candidate_1p20x: CAGR 20.92%, Sharpe 1.037, MaxDD -26.28%, Signals 467
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_10y
- legacy_no_buffer_1p00x: CAGR 30.38%, Sharpe 1.425, MaxDD -20.22%, Signals 614
- candidate_1p02x: CAGR 29.73%, Sharpe 1.405, MaxDD -20.34%, Signals 577
- candidate_1p05x: CAGR 28.98%, Sharpe 1.373, MaxDD -23.45%, Signals 550
- candidate_1p10x: CAGR 27.29%, Sharpe 1.317, MaxDD -24.05%, Signals 508
- candidate_1p15x: CAGR 23.41%, Sharpe 1.155, MaxDD -27.70%, Signals 489
- candidate_1p20x: CAGR 20.27%, Sharpe 1.025, MaxDD -26.28%, Signals 467
- Winner by Sharpe: legacy_no_buffer_1p00x
#### full_common
- legacy_no_buffer_1p00x: CAGR 24.79%, Sharpe 1.211, MaxDD -30.81%, Signals 614
- candidate_1p02x: CAGR 24.05%, Sharpe 1.183, MaxDD -34.32%, Signals 577
- candidate_1p05x: CAGR 22.54%, Sharpe 1.120, MaxDD -35.77%, Signals 550
- candidate_1p10x: CAGR 21.43%, Sharpe 1.078, MaxDD -40.33%, Signals 508
- candidate_1p15x: CAGR 18.22%, Sharpe 0.938, MaxDD -40.15%, Signals 489
- candidate_1p20x: CAGR 14.93%, Sharpe 0.799, MaxDD -39.48%, Signals 467
- Winner by Sharpe: legacy_no_buffer_1p00x

### mix2_60_20__70_20
#### last_3y
- legacy_no_buffer_1p00x: CAGR 25.47%, Sharpe 1.175, MaxDD -21.30%, Signals 618
- candidate_1p02x: CAGR 22.87%, Sharpe 1.075, MaxDD -23.99%, Signals 587
- candidate_1p05x: CAGR 22.50%, Sharpe 1.064, MaxDD -23.73%, Signals 563
- candidate_1p10x: CAGR 19.84%, Sharpe 0.962, MaxDD -24.72%, Signals 507
- candidate_1p15x: CAGR 14.99%, Sharpe 0.761, MaxDD -28.39%, Signals 491
- candidate_1p20x: CAGR 13.60%, Sharpe 0.705, MaxDD -28.09%, Signals 469
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_5y
- legacy_no_buffer_1p00x: CAGR 31.86%, Sharpe 1.446, MaxDD -21.30%, Signals 618
- candidate_1p05x: CAGR 30.77%, Sharpe 1.403, MaxDD -23.73%, Signals 563
- candidate_1p02x: CAGR 29.63%, Sharpe 1.357, MaxDD -23.99%, Signals 587
- candidate_1p10x: CAGR 28.04%, Sharpe 1.306, MaxDD -24.72%, Signals 507
- candidate_1p15x: CAGR 22.54%, Sharpe 1.089, MaxDD -28.39%, Signals 491
- candidate_1p20x: CAGR 19.14%, Sharpe 0.960, MaxDD -28.09%, Signals 469
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_10y
- legacy_no_buffer_1p00x: CAGR 29.56%, Sharpe 1.390, MaxDD -21.30%, Signals 618
- candidate_1p05x: CAGR 28.86%, Sharpe 1.362, MaxDD -23.73%, Signals 563
- candidate_1p02x: CAGR 28.07%, Sharpe 1.330, MaxDD -23.99%, Signals 587
- candidate_1p10x: CAGR 27.59%, Sharpe 1.320, MaxDD -24.72%, Signals 507
- candidate_1p15x: CAGR 22.10%, Sharpe 1.097, MaxDD -28.39%, Signals 491
- candidate_1p20x: CAGR 19.89%, Sharpe 1.007, MaxDD -28.09%, Signals 469
- Winner by Sharpe: legacy_no_buffer_1p00x
#### full_common
- legacy_no_buffer_1p00x: CAGR 23.08%, Sharpe 1.142, MaxDD -34.04%, Signals 618
- candidate_1p02x: CAGR 22.41%, Sharpe 1.113, MaxDD -31.99%, Signals 587
- candidate_1p05x: CAGR 22.16%, Sharpe 1.104, MaxDD -34.69%, Signals 563
- candidate_1p10x: CAGR 20.34%, Sharpe 1.033, MaxDD -39.35%, Signals 507
- candidate_1p15x: CAGR 16.92%, Sharpe 0.884, MaxDD -36.56%, Signals 491
- candidate_1p20x: CAGR 15.74%, Sharpe 0.835, MaxDD -36.98%, Signals 469
- Winner by Sharpe: legacy_no_buffer_1p00x

### mix2_60_20__50_20
#### last_3y
- candidate_1p02x: CAGR 23.61%, Sharpe 1.112, MaxDD -22.22%, Signals 588
- candidate_1p05x: CAGR 22.51%, Sharpe 1.077, MaxDD -21.54%, Signals 555
- legacy_no_buffer_1p00x: CAGR 22.56%, Sharpe 1.069, MaxDD -22.29%, Signals 633
- candidate_1p10x: CAGR 21.39%, Sharpe 1.031, MaxDD -24.64%, Signals 507
- candidate_1p15x: CAGR 21.28%, Sharpe 1.019, MaxDD -25.20%, Signals 483
- candidate_1p20x: CAGR 18.19%, Sharpe 0.894, MaxDD -24.27%, Signals 459
- Winner by Sharpe: candidate_1p02x
#### last_5y
- legacy_no_buffer_1p00x: CAGR 25.87%, Sharpe 1.222, MaxDD -22.29%, Signals 633
- candidate_1p02x: CAGR 25.38%, Sharpe 1.206, MaxDD -22.22%, Signals 588
- candidate_1p10x: CAGR 24.64%, Sharpe 1.189, MaxDD -24.64%, Signals 507
- candidate_1p05x: CAGR 24.65%, Sharpe 1.187, MaxDD -21.54%, Signals 555
- candidate_1p15x: CAGR 24.02%, Sharpe 1.157, MaxDD -25.20%, Signals 483
- candidate_1p20x: CAGR 19.47%, Sharpe 0.975, MaxDD -24.27%, Signals 459
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_10y
- legacy_no_buffer_1p00x: CAGR 29.15%, Sharpe 1.369, MaxDD -22.29%, Signals 633
- candidate_1p02x: CAGR 27.31%, Sharpe 1.302, MaxDD -22.22%, Signals 588
- candidate_1p05x: CAGR 26.16%, Sharpe 1.260, MaxDD -21.54%, Signals 555
- candidate_1p10x: CAGR 26.04%, Sharpe 1.255, MaxDD -24.64%, Signals 507
- candidate_1p15x: CAGR 23.62%, Sharpe 1.156, MaxDD -25.20%, Signals 483
- candidate_1p20x: CAGR 20.56%, Sharpe 1.033, MaxDD -24.27%, Signals 459
- Winner by Sharpe: legacy_no_buffer_1p00x
#### full_common
- legacy_no_buffer_1p00x: CAGR 22.91%, Sharpe 1.129, MaxDD -42.01%, Signals 633
- candidate_1p02x: CAGR 22.47%, Sharpe 1.114, MaxDD -41.71%, Signals 588
- candidate_1p05x: CAGR 21.28%, Sharpe 1.068, MaxDD -42.16%, Signals 555
- candidate_1p10x: CAGR 20.37%, Sharpe 1.031, MaxDD -43.89%, Signals 507
- candidate_1p15x: CAGR 17.73%, Sharpe 0.918, MaxDD -45.47%, Signals 483
- candidate_1p20x: CAGR 15.63%, Sharpe 0.824, MaxDD -45.15%, Signals 459
- Winner by Sharpe: legacy_no_buffer_1p00x

### formal_baseline_60_20
#### last_3y
- legacy_no_buffer_1p00x: CAGR 34.25%, Sharpe 1.487, MaxDD -17.37%, Signals 623
- candidate_1p02x: CAGR 31.83%, Sharpe 1.416, MaxDD -19.12%, Signals 586
- candidate_1p05x: CAGR 31.15%, Sharpe 1.396, MaxDD -18.91%, Signals 537
- candidate_1p15x: CAGR 31.26%, Sharpe 1.394, MaxDD -22.48%, Signals 472
- candidate_1p10x: CAGR 30.63%, Sharpe 1.371, MaxDD -21.36%, Signals 494
- candidate_1p20x: CAGR 27.73%, Sharpe 1.245, MaxDD -23.35%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_5y
- legacy_no_buffer_1p00x: CAGR 35.61%, Sharpe 1.575, MaxDD -17.37%, Signals 623
- candidate_1p02x: CAGR 33.39%, Sharpe 1.509, MaxDD -19.12%, Signals 586
- candidate_1p05x: CAGR 32.85%, Sharpe 1.493, MaxDD -18.91%, Signals 537
- candidate_1p15x: CAGR 31.03%, Sharpe 1.434, MaxDD -22.48%, Signals 472
- candidate_1p10x: CAGR 29.70%, Sharpe 1.381, MaxDD -21.36%, Signals 494
- candidate_1p20x: CAGR 27.61%, Sharpe 1.289, MaxDD -23.35%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x
#### last_10y
- legacy_no_buffer_1p00x: CAGR 33.74%, Sharpe 1.548, MaxDD -20.00%, Signals 623
- candidate_1p05x: CAGR 32.64%, Sharpe 1.511, MaxDD -20.20%, Signals 537
- candidate_1p02x: CAGR 31.97%, Sharpe 1.492, MaxDD -20.22%, Signals 586
- candidate_1p10x: CAGR 28.60%, Sharpe 1.362, MaxDD -21.36%, Signals 494
- candidate_1p15x: CAGR 26.79%, Sharpe 1.293, MaxDD -22.48%, Signals 472
- candidate_1p20x: CAGR 24.23%, Sharpe 1.183, MaxDD -23.35%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x
#### full_common
- legacy_no_buffer_1p00x: CAGR 30.88%, Sharpe 1.452, MaxDD -31.65%, Signals 623
- candidate_1p02x: CAGR 29.61%, Sharpe 1.407, MaxDD -31.59%, Signals 586
- candidate_1p05x: CAGR 28.94%, Sharpe 1.378, MaxDD -33.66%, Signals 537
- candidate_1p10x: CAGR 24.16%, Sharpe 1.189, MaxDD -41.96%, Signals 494
- candidate_1p15x: CAGR 22.91%, Sharpe 1.138, MaxDD -40.51%, Signals 472
- candidate_1p20x: CAGR 20.27%, Sharpe 1.027, MaxDD -44.05%, Signals 454
- Winner by Sharpe: legacy_no_buffer_1p00x