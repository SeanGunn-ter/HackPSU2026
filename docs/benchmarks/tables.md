## First run

| pipeline | rows | pandas, s (min-max) | incpandas (min-max) | speedup run 1 | speedup run 2 |
|---|---|---|---|---|---|
| `df.qty.sum()` | 1M | 0.159 (0.157-0.162) | 0.183 (0.182-0.184) | 0.9x | 0.9x |
| `(df.qty * df.price).sum()` | 1M | 0.202 (0.193-0.212) | 0.207 (0.190-0.223) | 1.0x | 1.0x |
| filter + groupby agg | 1M | 0.375 (0.281-0.468) | 0.282 (0.282-0.282) | 1.3x | 1.1x |
| left merge + groupby | 1M | 0.424 (0.316-0.532) | 0.318 (0.311-0.324) | 1.3x | 1.1x |
| row-wise filter (large output) | 1M | 0.197 (0.185-0.209) | 0.228 (0.211-0.244) | 0.9x | 0.8x |
| `df.qty.sum()` | 5M | 1.076 (0.907-1.245) | 0.964 (0.946-0.982) | 1.1x | 1.2x |
| `(df.qty * df.price).sum()` | 5M | 1.117 (0.885-1.349) | 0.965 (0.902-1.028) | 1.2x | 1.0x |
| filter + groupby agg | 5M | 2.313 (2.062-2.564) | 1.612 (1.430-1.794) | 1.4x | 1.4x |
| left merge + groupby | 5M | 2.501 (2.452-2.550) | 2.018 (1.751-2.284) | 1.2x | 1.3x |
| row-wise filter (large output) | 5M | 1.138 (1.050-1.225) | 1.729 (1.610-1.849) | 0.7x | 0.9x |
| `df.qty.sum()` | 20M | 4.581 (3.835-5.327) | 5.721 (5.257-6.184) | 0.8x | 0.8x |
| `(df.qty * df.price).sum()` | 20M | 5.204 (4.944-5.463) | 6.196 (5.467-6.924) | 0.8x | 0.9x |
| filter + groupby agg | 20M | 8.788 (7.311-10.266) | 8.429 (7.786-9.073) | 1.0x | 1.1x |
| left merge + groupby | 20M | 11.664 (10.653-12.675) | 10.892 (10.612-11.172) | 1.1x | 1.1x |
| row-wise filter (large output) | 20M | 5.598 (3.876-7.321) | 6.875 (6.787-6.964) | 0.8x | 0.9x |

## Rerun after appending 1,000 rows

| pipeline | rows | pandas, s (min-max) | incpandas (min-max) | speedup run 1 | speedup run 2 |
|---|---|---|---|---|---|
| `df.qty.sum()` | 1M | 0.177 (0.172-0.186) | 0.017 (0.016-0.018) | 10.3x | 12.6x |
| `(df.qty * df.price).sum()` | 1M | 0.186 (0.177-0.208) | 0.018 (0.017-0.020) | 10.4x | 11.7x |
| filter + groupby agg | 1M | 0.274 (0.266-0.342) | 0.018 (0.017-0.021) | 15.5x | 14.4x |
| left merge + groupby | 1M | 0.328 (0.322-0.482) | 0.020 (0.019-0.030) | 16.2x | 16.4x |
| row-wise filter (large output) | 1M | 0.187 (0.183-0.187) | 0.036 (0.035-0.039) | 5.2x | 6.7x |
| `df.qty.sum()` | 5M | 0.890 (0.832-1.279) | 0.074 (0.074-0.076) | 12.0x | 11.9x |
| `(df.qty * df.price).sum()` | 5M | 0.889 (0.846-1.399) | 0.071 (0.068-0.076) | 12.5x | 11.4x |
| filter + groupby agg | 5M | 2.440 (1.683-2.721) | 0.079 (0.078-0.086) | 31.0x | 33.1x |
| left merge + groupby | 5M | 2.375 (2.220-2.626) | 0.082 (0.079-0.090) | 29.1x | 27.5x |
| row-wise filter (large output) | 5M | 0.964 (0.941-1.632) | 0.192 (0.185-0.227) | 5.0x | 8.1x |
| `df.qty.sum()` | 20M | 5.725 (3.998-6.063) | 0.276 (0.272-0.320) | 20.7x | 17.5x |
| `(df.qty * df.price).sum()` | 20M | 6.008 (5.450-6.203) | 0.281 (0.279-0.341) | 21.4x | 20.3x |
| filter + groupby agg | 20M | 7.507 (7.314-7.668) | 0.276 (0.271-0.287) | 27.2x | 28.0x |
| left merge + groupby | 20M | 10.457 (10.342-11.166) | 0.283 (0.281-0.308) | 37.0x | 35.5x |
| row-wise filter (large output) | 20M | 6.248 (5.198-6.566) | 0.766 (0.753-0.786) | 8.2x | 7.6x |

## Rerun, file unchanged

| pipeline | rows | pandas, s (min-max) | incpandas (min-max) | speedup run 1 | speedup run 2 |
|---|---|---|---|---|---|
| `df.qty.sum()` | 1M | 0.175 (0.170-0.193) | 3.9 ms (3.8-4.0) | 44.5x | 62.1x |
| `(df.qty * df.price).sum()` | 1M | 0.187 (0.174-0.225) | 5.3 ms (4.5-6.7) | 35.2x | 58.1x |
| filter + groupby agg | 1M | 0.285 (0.277-0.294) | 4.8 ms (4.5-6.2) | 59.2x | 61.5x |
| left merge + groupby | 1M | 0.323 (0.313-0.336) | 7.7 ms (7.4-7.7) | 42.2x | 41.4x |
| row-wise filter (large output) | 1M | 0.186 (0.185-0.257) | 0.027 (0.026-0.038) | 6.8x | 9.8x |
| `df.qty.sum()` | 5M | 0.883 (0.842-1.326) | 4.5 ms (4.1-4.8) | 195.0x | 192.8x |
| `(df.qty * df.price).sum()` | 5M | 0.885 (0.869-1.322) | 3.6 ms (3.3-4.0) | 246.1x | 242.8x |
| filter + groupby agg | 5M | 2.395 (1.674-2.630) | 5.8 ms (5.4-6.2) | 414.5x | 282.4x |
| left merge + groupby | 5M | 2.098 (1.596-2.578) | 8.9 ms (8.8-12.6) | 237.0x | 227.6x |
| row-wise filter (large output) | 5M | 1.360 (0.934-1.749) | 0.119 (0.118-0.127) | 11.4x | 12.6x |
| `df.qty.sum()` | 20M | 5.184 (5.100-5.192) | 2.9 ms (2.9-3.6) | 1767.0x | 1567.2x |
| `(df.qty * df.price).sum()` | 20M | 6.256 (5.990-6.686) | 3.5 ms (3.4-3.9) | 1767.7x | 1534.0x |
| filter + groupby agg | 20M | 7.576 (7.340-7.703) | 5.2 ms (5.1-5.4) | 1452.9x | 1540.7x |
| left merge + groupby | 20M | 10.816 (10.634-11.163) | 9.8 ms (9.2-11.7) | 1103.6x | 1136.5x |
| row-wise filter (large output) | 20M | 6.301 (5.954-6.413) | 0.490 (0.489-0.516) | 12.9x | 11.3x |

## Default change detection vs INCPANDAS_CHECK=exact (run 1 vs the exact run)

| pipeline | rows | scenario | default: incpandas | default speedup | exact: incpandas | exact speedup |
|---|---|---|---|---|---|---|
| `df.qty.sum()` | 1M | append | 0.017 (0.016-0.018) | 10.3x | 0.014 (0.013-0.015) | 11.6x |
| `df.qty.sum()` | 1M | no change | 3.9 ms (3.8-4.0) | 44.5x | 0.013 (0.012-0.015) | 13.4x |
| `(df.qty * df.price).sum()` | 1M | append | 0.018 (0.017-0.020) | 10.4x | 0.014 (0.014-0.021) | 12.0x |
| `(df.qty * df.price).sum()` | 1M | no change | 5.3 ms (4.5-6.7) | 35.2x | 0.012 (0.012-0.013) | 12.8x |
| filter + groupby agg | 1M | append | 0.018 (0.017-0.021) | 15.5x | 0.018 (0.017-0.018) | 14.4x |
| filter + groupby agg | 1M | no change | 4.8 ms (4.5-6.2) | 59.2x | 0.015 (0.014-0.015) | 18.3x |
| left merge + groupby | 1M | append | 0.020 (0.019-0.030) | 16.2x | 0.020 (0.020-0.020) | 15.6x |
| left merge + groupby | 1M | no change | 7.7 ms (7.4-7.7) | 42.2x | 0.017 (0.017-0.021) | 17.3x |
| row-wise filter (large output) | 1M | append | 0.036 (0.035-0.039) | 5.2x | 0.026 (0.025-0.026) | 6.3x |
| row-wise filter (large output) | 1M | no change | 0.027 (0.026-0.038) | 6.8x | 0.025 (0.024-0.028) | 6.5x |
| `df.qty.sum()` | 5M | append | 0.074 (0.074-0.076) | 12.0x | 0.076 (0.074-0.084) | 11.6x |
| `df.qty.sum()` | 5M | no change | 4.5 ms (4.1-4.8) | 195.0x | 0.075 (0.074-0.083) | 11.4x |
| `(df.qty * df.price).sum()` | 5M | append | 0.071 (0.068-0.076) | 12.5x | 0.077 (0.074-0.081) | 11.8x |
| `(df.qty * df.price).sum()` | 5M | no change | 3.6 ms (3.3-4.0) | 246.1x | 0.075 (0.070-0.092) | 12.2x |
| filter + groupby agg | 5M | append | 0.079 (0.078-0.086) | 31.0x | 0.079 (0.078-0.082) | 28.7x |
| filter + groupby agg | 5M | no change | 5.8 ms (5.4-6.2) | 414.5x | 0.077 (0.075-0.094) | 29.9x |
| left merge + groupby | 5M | append | 0.082 (0.079-0.090) | 29.1x | 0.082 (0.081-0.096) | 29.0x |
| left merge + groupby | 5M | no change | 8.9 ms (8.8-12.6) | 237.0x | 0.080 (0.078-0.088) | 27.6x |
| row-wise filter (large output) | 5M | append | 0.192 (0.185-0.227) | 5.0x | 0.193 (0.189-0.204) | 7.7x |
| row-wise filter (large output) | 5M | no change | 0.119 (0.118-0.127) | 11.4x | 0.186 (0.184-0.190) | 4.8x |

## Saved state and where an append rerun goes (run 1)

| pipeline | rows | CSV size | saved state on disk | rerun after append | of which: read + hash file | load saved state |
|---|---|---|---|---|---|---|
| `df.qty.sum()` | 1M | 10 MB | 1 KB | 17 ms | 9 ms (52%) | 0 ms (1%) |
| `(df.qty * df.price).sum()` | 1M | 10 MB | 1 KB | 18 ms | 9 ms (50%) | 0 ms (0%) |
| filter + groupby agg | 1M | 10 MB | 3 KB | 18 ms | 9 ms (50%) | 0 ms (2%) |
| left merge + groupby | 1M | 10 MB | 4 KB | 20 ms | 9 ms (47%) | 0 ms (2%) |
| row-wise filter (large output) | 1M | 10 MB | 15.5 MB | 36 ms | 9 ms (26%) | 10 ms (28%) |
| `df.qty.sum()` | 5M | 50 MB | 1 KB | 74 ms | 66 ms (89%) | 0 ms (0%) |
| `(df.qty * df.price).sum()` | 5M | 50 MB | 1 KB | 71 ms | 71 ms (100%) | 0 ms (0%) |
| filter + groupby agg | 5M | 50 MB | 3 KB | 79 ms | 70 ms (89%) | 0 ms (0%) |
| left merge + groupby | 5M | 50 MB | 4 KB | 82 ms | 69 ms (85%) | 0 ms (0%) |
| row-wise filter (large output) | 5M | 50 MB | 77.3 MB | 192 ms | 67 ms (35%) | 93 ms (49%) |
| `df.qty.sum()` | 20M | 199 MB | 1 KB | 276 ms | 276 ms (100%) | 0 ms (0%) |
| `(df.qty * df.price).sum()` | 20M | 199 MB | 1 KB | 281 ms | 274 ms (97%) | 0 ms (0%) |
| filter + groupby agg | 20M | 199 MB | 3 KB | 276 ms | 281 ms (102%) | 0 ms (0%) |
| left merge + groupby | 20M | 199 MB | 4 KB | 283 ms | 265 ms (94%) | 0 ms (0%) |
| row-wise filter (large output) | 20M | 199 MB | 309.1 MB | 766 ms | 262 ms (34%) | 361 ms (47%) |
