# Reproduction Report

## Claim comparison

| C_i | Type | Paper result | Replication result | Agent comparison |
| --- | --- | --- | --- | --- |
| C1 | validation | {initial sepsis records: 36613; outlier exclusions: {urine: 13; fluids: 12}; premature death exclusions: 870; SOFA criterion exclusions: 503; total excluded: 1398; final records: 35215} | 26,191 candidate stays; current P2 sequential exclusions: urine 1, fluid 2, early death 434, SOFA 2,921 (3,358 total); final 22,833. C1/V1 retain stale early-death/SOFA values 435/2,927 (3,365 total), inconsistent with the same final count. | not close |
| C2 | validation | {age mean sd: 65.4 ± 16.3; female: 44.5%; hospital mortality: 14.5%; 90 day mortality table: 25.1%; 90 day mortality prose: 25.5%; LOS days mean sd: 5.1 ± 7.1; septic shock: 12.4%; SOFA mean sd: 5.5 ± 2.8; NEWS mean sd: 6.06 ± 2.57; mechanical ventilation: 35.1%; vasopressor: 16.9%; antibiotics: 66.3%} | age 66.2259 ± 15.4199 (n=22,833); female 41.1028%; hospital mortality 19.1039%; LOS 6.5374 ± 8.0178 days; SOFA 2.6761 ± 2.9390; NEWS 1.2948 ± 1.8462. 90-day mortality, septic shock, mechanical ventilation, vasopressor use, and antibiotics given were not produced. | not assessable |
| C3 | validation | {survivor n: 30105; non survivor n: 5110; age median IQR: {survivors: 66.0 [55.0–77.0]; non survivors: 71.0 [60.0–81.0]; p: <0.001}; Charlson median IQR: {survivors: 5.0 [3.0–7.0]; non survivors: 6.0 [4.0–9.0]; p: <0.001}; SOFA median IQR: {survivors: 5.0 [3.0–7.0]; non survivors: 7.0 [5.0–9.0]; p: <0.001}; NEWS median IQR: {survivors: 6.0 [4.0–7.0]; non survivors: 7.0 [6.0–9.0]; p: <0.001}; lactate median IQR: {survivors: 1.6 [1.1–2.4]; non survivors: 2.0 [1.3–3.3]; p: <0.001}; sex p: 0.103; temperature p: 1.000} | survivors n=18,471 vs non-survivors n=4,362; age 67 [56–76] vs 71 [60–81], p=1.389e-58; Charlson 1 [0–4] vs 2 [0–5], p=6.693e-26; SOFA 2 [0–4] vs 3 [1–6], p=5.155e-95; NEWS 0 [0–2] vs 1 [0–3], p=6.687e-114; lactate 1.7 [1.2–2.55] vs 2.15 [1.4–3.7], p=3.532e-97; female 40.3118% vs 44.4521%, sex p=6.309e-7; temperature 36.2 [35.5775–37.155] vs 36.3536 [35.0083–37.5], p=0.4539. | not close |
| C4 | final | {XGBoost: {AUROC: 0.871 (0.861–0.882); AUPRC: 0.594 (0.563–0.626); accuracy: 0.878 (0.870–0.885); Brier: 0.088; ECE: 0.029}; LightGBM: {AUROC: 0.869 (0.858–0.880); AUPRC: 0.589 (0.558–0.621); accuracy: 0.878 (0.870–0.886); Brier: 0.089; ECE: 0.022}; Transformer: {AUROC: 0.866 (0.854–0.877); AUPRC: 0.583 (0.552–0.614); accuracy: 0.878 (0.870–0.885); Brier: 0.09; ECE: 0.049}; RandomForest: {AUROC: 0.850 (0.838–0.862); AUPRC: 0.547 (0.515–0.580); accuracy: 0.873 (0.865–0.881); Brier: 0.094; ECE: 0.076}; LSTM: {AUROC: 0.847 (0.834–0.858); AUPRC: 0.529 (0.497–0.561); accuracy: 0.868 (0.860–0.875); Brier: 0.104; ECE: 0.135}; Linear: {AUROC: 0.843 (0.831–0.855); AUPRC: 0.530 (0.497–0.563); accuracy: 0.870 (0.861–0.878); Brier: 0.095; ECE: 0.04}; SOFA: {AUROC: 0.730 (0.718–0.742); AUPRC: 0.282 (0.246–0.320); accuracy: 0.810 (0.793–0.827); Brier: 0.125; ECE: 0.182}; NEWS: {AUROC: 0.697 (0.684–0.710); AUPRC: 0.252 (0.218–0.289); accuracy: 0.801 (0.785–0.818); Brier: 0.134; ECE: 0.21}} | XGBoost: AUROC 0.833307 (0.826630–0.840456), AUPRC 0.583004 (0.566786–0.599240), accuracy 0.836204 (0.830831–0.841577), Brier 0.118114, ECE 0.033158; LightGBM: 0.835538 (0.828928–0.842855), 0.587113 (0.571786–0.603083), 0.837876 (0.832759–0.843197), 0.116882, 0.025830; Transformer: 0.762628 (0.754523–0.771130), 0.451044 (0.435040–0.469269), 0.800588 (0.794658–0.806415), 0.168349, 0.147827; Random Forest: 0.815855 (0.808761–0.823278), 0.551870 (0.536342–0.567184), 0.833215 (0.827743–0.838487), 0.121546, 0.022310; LSTM: 0.727280 (0.717428–0.736680), 0.444565 (0.429333–0.461250), 0.791874 (0.786299–0.797549), 0.195439, 0.190537; Linear: 0.813370 (0.806143–0.820464), 0.548119 (0.532645–0.563856), 0.830327 (0.824754–0.835244), 0.122385, 0.015975; SOFA: 0.685946 (0.675967–0.695243), 0.362471 (0.349276–0.376681), 0.550208 (0.543264–0.557208), 0.271945, 0.303146; NEWS: 0.592784 (0.583257–0.602423), 0.280133 (0.268599–0.292381), 0.552893 (0.546256–0.559940), 0.291276, 0.303146. Metric order is AUROC, AUPRC, accuracy, Brier, ECE; current V3 differs slightly from C4's embedded LightGBM row. | not close |
| C5 | final | XGBoost had the highest reported mortality AUROC (0.871) and AUPRC (0.594), outperforming the linear, SOFA, and NEWS baselines. | LightGBM ranks first (AUROC/AUPRC 0.835538/0.587113), ahead of XGBoost (0.833307/0.583004). XGBoost exceeds Linear (0.813370/0.548119), SOFA (0.685946/0.362471), and NEWS (0.592784/0.280133), but is not the reproduced top model; C5's embedded LightGBM values differ slightly from current V3. | not close |
| C6 | final | {DeLong vs linear: XGBoost, LightGBM, and Transformer p<0.001; lowest Brier: XGBoost 0.088; lowest ECE: LightGBM 0.022} | DeLong p versus Linear: XGBoost 7.904e-16, LightGBM 3.314e-19, Transformer 2.680e-38 (all <0.001). Lowest reproduced Brier is LightGBM 0.116882, not XGBoost; lowest ECE is Linear 0.015975 (or Random Forest 0.022310 when Linear is excluded), not LightGBM. C6's embedded LightGBM row is stale relative to current V3. | not close |
| C7 | validation | {RandomForest: {FP: 85; FN: 776}; Transformer: {TP: 284; FP: 102; FN: 729}; LightGBM: {TP: 364; FP: 177}; XGBoost: {TP: 353; FP: 168}} | TN/FP/FN/TP: XGBoost 15,140/712/2,521/1,365; LightGBM 15,111/741/2,447/1,439; Transformer 14,246/1,606/2,330/1,556; Random Forest 15,326/526/2,766/1,120. | not close |
| C8 | validation | Oxygen Flow Device; Charlson Comorbidity Index; SOFA Score; NEWS Score | top mean-absolute-SHAP ranks: RASS t0 0.306884, Oxygen Flow Device t0 0.242111, Uo Step t0 0.236587, Urea Nitrogen t0 0.217625; Charlson t−5 is rank 8 (0.098405). SOFA and NEWS are absent from the reproduced top 15. | not close |
| C9 | validation | High Oxygen Flow Device, Charlson Comorbidity Index, and SOFA Score values aligned with positive SHAP values/increased mortality risk; high Uo Step aligned with lower risk. | the reproduced beeswarm supports high Oxygen Flow Device and Charlson values on the positive-SHAP side and high Uo Step t0 on the negative side; it uses different Uo time positions, ranks RASS first, and produces no SOFA row or SOFA directional result. | not close |
| C10 | validation | {output log odds: 3.042; baseline log odds: -2.582; contributions: {Charlson: 0.5; SOFA: 0.45; NEWS: 0.33; lactate: 0.35}} | selected mortality explanation: baseline −1.484311, tabular raw/additive output 6.633857, prediction 0.998687; lactate t0 contribution +0.834858. Charlson, SOFA, and NEWS contributions were not produced. The PNG instead labels f(x)=3.752 with the same baseline, conflicting with the table. | not assessable |
| C11 | final | {female: {AUROC: 0.864 (0.844–0.879); AUPRC: 0.582 (0.531–0.626)}; male: {AUROC: 0.877 (0.863–0.890); AUPRC: 0.603 (0.562–0.643)}; age 18 40: {AUROC: 0.935 (0.902–0.965); AUPRC: 0.646 (0.526–0.767)}; age 41 65: {AUROC: 0.875 (0.854–0.893); AUPRC: 0.579 (0.528–0.635)}; age 66 80: {AUROC: 0.871 (0.851–0.890); AUPRC: 0.619 (0.568–0.670)}; age over 80: {AUROC: 0.826 (0.799–0.853); AUPRC: 0.586 (0.523–0.650)}} | female n=8,166, AUROC 0.824380 (0.813539–0.835250), AUPRC 0.599610 (0.576704–0.624060); male n=11,572, 0.839465 (0.830938–0.848128), 0.570524 (0.547253–0.591723); age 18–40 n=1,419, 0.858045 (0.828250–0.887219), 0.568352 (0.499030–0.642648); age 41–65 n=7,295, 0.850309 (0.839239–0.861078), 0.564482 (0.537709–0.591956); age 66–80 n=7,404, 0.837327 (0.827103–0.847948), 0.591689 (0.564506–0.617913); age >80 n=3,620, 0.789955 (0.774566–0.806425), 0.624599 (0.594139–0.654920). | not close |
| C12 | final | {LightGBM: {RMSE: 4.826 (±0.205); MAE: 2.541 (±0.035); MSE: 23.297}; XGBoost: {RMSE: 4.879 (±0.215); MAE: 2.584 (±0.038); MSE: 23.81}; LSTM: {RMSE: 4.918 (4.617–5.232); MAE: 2.618 (2.522–2.712); MSE: 24.186}; RandomForest: {RMSE: 4.934 (±0.172); MAE: 2.637 (±0.031); MSE: 24.349}; Lasso: {RMSE: 5.465 (±0.284); MAE: 3.097 (±0.052); MSE: 29.876}; Transformer: {RMSE: 6.726 (6.309–7.131); MAE: 4.106 (3.976–4.228); MSE: 45.239}} | LightGBM: RMSE 7.189054 [6.813964–7.621730], MAE 4.133252 [4.050242–4.222667], MSE 51.682504; XGBoost: 7.339318 [6.952655–7.779986], 4.178273 [4.092162–4.267412], 53.865588; LSTM: 8.039998 [7.702623–8.445394], 4.415432 [4.319023–4.512412], 64.641564; Random Forest: 7.435341 [7.069616–7.852955], 4.411166 [4.326825–4.498354], 55.284294; Lasso: 7.517051 [7.135527–7.959551], 4.562203 [4.478567–4.647044], 56.506057; Transformer: 7.897027 [7.557122–8.294467], 4.494873 [4.403263–4.585017], 62.363029. | not close |
| C13 | final | LightGBM had the lowest reported remaining-LOS error (RMSE 4.826 ±0.205; MAE 2.541 ±0.035), followed by XGBoost; Transformer had the highest reported errors. | reproduced RMSE order and RMSE/MAE/MSE: LightGBM 7.189054/4.133252/51.682504; XGBoost 7.339318/4.178273/53.865588; Random Forest 7.435341/4.411166/55.284294; Lasso 7.517051/4.562203/56.506057; Transformer 7.897027/4.494873/62.363029; LSTM 8.039998/4.415432/64.641564. | not close |
| C14 | validation | Uo Total (first); Oxygen Flow Device (second); fluid balance (third); Glasgow Coma Scale | top ranks are Oxygen Flow Device t0 2.288156, Uo Total t−5 1.028335, SOFA t0 0.235981, and RASS t0 0.231968. Fluid balance and GCS are absent from the reproduced top 15. | not close |
| C15 | validation | High Uo Total, Oxygen Flow Device, and fluid-balance values had long rightward SHAP tails and increased predicted LOS; low values clustered near baseline. | V12 serializes only unsigned mean-absolute-SHAP ranks: Oxygen Flow Device t0 first (2.288156), Uo Total t−5 second (1.028335), Uo Total t−4 tenth (0.157498), with no fluid-balance row. The beeswarm visually supports a high-value/rightward pattern for Oxygen Flow Device, but not the paper's low-values-near-baseline condition; the complete three-feature directional result was not produced. | not assessable |
| C16 | validation | {paper reported predicted LOS days: 47; expected baseline days: 5.2; UoTotal t5 contribution days: 23.84} | selected stay 34,840,737: baseline 6.232846 days, tabular prediction/raw output 35.997374 days, Uo Total t−5 contribution +1.575482 days. The PNG instead labels f(x)=32.404 and E[f(X)]=6.233, conflicting with the table. | not close |
| C17 | final | {XGBoost: {AUROC: 0.950 (0.949–0.951); AUPRC: 0.753 (0.748–0.758); accuracy: 0.955 (0.954–0.956); Brier: 0.036; ECE: 0.071}; LightGBM: {AUROC: 0.950 (0.949–0.951); AUPRC: 0.738 (0.730–0.746); accuracy: 0.953 (0.952–0.954); Brier: 0.037; ECE: 0.011}; RandomForest: {AUROC: 0.938 (0.936–0.940); AUPRC: 0.692 (0.686–0.698); accuracy: 0.946 (0.945–0.947); Brier: 0.041; ECE: 0.098}; LogisticRegression: {AUROC: 0.896 (0.894–0.898); AUPRC: 0.485 (0.478–0.492); accuracy: 0.932 (0.931–0.933); Brier: 0.053; ECE: 0.058}; LSTM: {AUROC: 0.878 (0.875–0.881); AUPRC: 0.516 (0.507–0.524); accuracy: 0.930 (0.929–0.931); Brier: 0.06; ECE: 0.188}; Transformer: {AUROC: 0.667 (0.663–0.670); AUPRC: 0.187 (0.182–0.192); accuracy: 0.921 (0.920–0.922); Brier: 0.069; ECE: 0.04}} | XGBoost: AUROC 0.924805 (0.907990–0.941832), AUPRC 0.114603 (0.086796–0.150189), accuracy 0.996440 (0.996033–0.996860), Brier 0.003470, ECE 0.003198; LightGBM: 0.880432 (0.859030–0.901404), 0.059446 (0.044552–0.083092), 0.995685 (0.995265–0.996153), 0.004155, 0.004128; Random Forest: 0.811076 (0.782384–0.841063), 0.051623 (0.038411–0.074830), 0.996428 (0.996021–0.996848), 0.003511, 0.001052; Logistic Regression: 0.891573 (0.867697–0.912265), 0.080283 (0.060307–0.109654), 0.995673 (0.995230–0.996117), 0.003968, 0.002529; LSTM: 0.680414 (0.649266–0.710955), 0.022845 (0.016076–0.034091), 0.995470 (0.995002–0.995949), 0.004289, 0.004307; Transformer: 0.483836 (0.454995–0.512278), 0.003264 (0.002881–0.003718), 0.996428 (0.996021–0.996848), 0.003563, 0.002083. | not close |
| C18 | final | {top AUROC: XGBoost and LightGBM: 0.950; significant vs logistic: XGBoost, LightGBM, Random Forest: p<0.001; lowest ECE: LightGBM: 0.011; lowest Brier: XGBoost: 0.036} | XGBoost AUROC 0.924805, p=0.001237 versus Logistic Regression, Brier 0.003470, ECE 0.003198; LightGBM AUROC 0.880432, p=0.373306, Brier 0.004155, ECE 0.004128; Random Forest p=9.954e-9 and ECE 0.001052. LightGBM does not tie for top AUROC, only Random Forest among the named tree models meets p<0.001, XGBoost remains the Brier minimum, and Random Forest—not LightGBM—has the ECE minimum. | not close |
| C19 | validation | {threshold: 0.5; true negatives: 60596; false positives: 590; false negatives: 2351} | at threshold 0.5, TN 83,136; FP 1; FN 296; TP 2. | not close |
| C20 | validation | Balance t-0; SOFA cardiovascular component at t-5 and t-0; platelets; PT; WBC | top reproduced ranks are lactate t0 0.829612, Balance t0 0.423458, SOFA CV t−1 0.311302, lactate t−4 0.180314, and total CO2 t0 0.171769; SOFA CV t0 is rank 7 (0.156367). Balance is not first; SOFA CV t−5, platelets, PT, and WBC are absent from the top 15. | not close |
| C21 | validation | Elevated fluid balance at t-0 and cardiovascular SOFA values consistently shift predictions toward higher septic-shock probability. | the beeswarm shows high-value Balance t0, SOFA CV t−1, and SOFA CV t0 points extending to the positive-SHAP side, but Balance ranks second behind lactate and SOFA CV t−5/t−2/t−3/t−4 are absent; the table itself contains only unsigned mean-absolute values. | not close |
| C22 | validation | {baseline log odds: -3.716; output log odds: 3.163; contributions: {Balance t0: 1.92; SOFA Cv t0: 0.6; SOFA Cv t2: 0.57}} | selected stay 36,223,000: baseline −6.147394; raw/additive output 1.009043/1.009046 log-odds; prediction 0.732833; Balance t0 +0.751748; SOFA CV t0 +0.332405; SOFA CV t−1 +0.573383. SOFA CV t−2 was not produced. The PNG instead labels f(x)=0.051 with the same baseline, conflicting with the table. | not assessable |
| C23 | final | {abstract AUROC: 0.874; Table 5 AUROC: 0.871; audit observation: The abstract and Table 5 report different XGBoost hospital-mortality AUROC values.} | the reproduced XGBoost mortality row has AUROC 0.833307 (95% CI 0.826630–0.840456), AUPRC 0.583004, accuracy 0.836204, Brier 0.118114, and ECE 0.033158; no separate abstract-specific output was produced. | close |

## Artifact reproduction

| Paper artifact | Reproduced artifact path | Assessment |
| --- | --- | --- |
| Table 1. List of main predictor variables used in the models, grouped by clinical category. | not produced | not assessable — no reproduced grouped predictor table was produced |
| Table 2. Cohort characteristics (extended from [20]). | `codegen/codebase/outputs/V1/results.parquet` | not assessable — the structured counterpart omits 90-day mortality, septic shock, mechanical ventilation, vasopressor use, and antibiotics, while several produced values differ |
| Table 3. Statistical data for survivor and non-survivor groups. | `codegen/codebase/outputs/V2/results.parquet` | not close — survivor/non-survivor counts, medians/IQRs, and the sex significance result differ materially |
| Figure 1. Dynamic sliding window for septic shock prediction. At each window step K, observation window features (past 24 h) were extracted to predict whether septic shock would occur at any point during the prediction horizon (next 24 h). The timeline illustrates the 4-h temporal shift between steps K and K + 1. | not produced | not assessable — no reproduced timeline or schematic was produced |
| Table 4. Task descriptions. | not produced | not assessable — no reproduced task-description table was produced |
| Table 5. Results for mortality prediction. | `codegen/codebase/outputs/V3/results.parquet`<br>`codegen/codebase/outputs/V4/results.parquet` | not close — all eight benchmark rows and metric fields exist, but values and the top-model/calibration-winner ordering differ |
| Figure 2. Confusion matrices for mortality task for the four best algorithms. | `codegen/codebase/outputs/V5/figures/M1.png`<br>`codegen/codebase/outputs/V5/figures/M2.png`<br>`codegen/codebase/outputs/V5/figures/M3.png`<br>`codegen/codebase/outputs/V5/figures/M4.png` | not close — the four 2×2 matrices and class layout were reproduced, but the reported cell counts differ materially |
| Figure 3. Top 15 features ranked by mean absolute SHAP value for mortality prediction for XGBoost. | `codegen/codebase/outputs/V6/figures/shap_bar.png` | not close — RASS is first, Oxygen Flow Device is second, Charlson is eighth, and SOFA/NEWS are missing from the reproduced top 15 |
| Figure 4. SHAP bee swarm plot for mortality used by the XGBoost model. | `codegen/codebase/outputs/V7/figures/shap_beeswarm.png` | not close — some directions agree, but the Uo time positions and ranking differ and the required SOFA row is absent |
| Figure 5. SHAP waterfall plot for mortality used by the XGBoost model. | `codegen/codebase/outputs/V8/figures/shap_waterfall.png` | not close — baseline, output, displayed drivers, and contributions differ; the PNG output also conflicts with V8's tabular output |
| Table 6. Subgroup fairness analysis (AUROC and AUPRC with 95% CI) of the XGBoost model for the mortality task. | `codegen/codebase/outputs/V9/results.parquet` | not close — all six subgroup rows exist, but counts and multiple point estimates/CIs differ |
| Table 7. Results for remaining length of stay prediction (after 24-h observation.) | `codegen/codebase/outputs/V10/results.parquet` | not close — the six models and RMSE/MAE/MSE fields exist, but numerical entries and ordering differ |
| Figure 6. Top 15 features ranked by mean absolute SHAP value for LOS task used by LightGBM. | `codegen/codebase/outputs/V11/figures/shap_bar.png` | not close — Oxygen Flow Device and Uo Total are reversed and fluid balance/GCS are absent |
| Figure 7. SHAP bee swarm plot for LOS used by the LightGBM model. | `codegen/codebase/outputs/V12/figures/shap_beeswarm.png` | not assessable — the fluid-balance row is absent and the persisted data contain no signed SHAP values, so the complete three-feature directional claim cannot be assessed |
| Figure 8. SHAP waterfall plot for LOS used by the LightGBM model. | `codegen/codebase/outputs/V13/figures/shap_waterfall.png` | not close — baseline, prediction, Uo Total contribution/rank, labels, and aggregation differ; the PNG conflicts with V13's table |
| Table 8. Results for septic shock prediction. | `codegen/codebase/outputs/V14/results.parquet` | not close — all six model rows and metric fields exist, but values, CIs, and AUROC ordering differ |
| Figure 9. Confusion matrix for septic shock task using XGBoost. | `codegen/codebase/outputs/V15/figures/M13.png` | not close — the plot structure matches but none of the four confusion-matrix cells matches |
| Figure 10. Top 15 features ranked by mean absolute SHAP value for septic shock prediction using XGBoost. | `codegen/codebase/outputs/V16/figures/shap_bar.png` | not close — lactate rather than Balance is first, several cardiovascular-SOFA time points are absent, and platelets/PT/WBC are missing |
| Figure 11. SHAP bee swarm plot for septic shock prediction used by the XGBoost model. | `codegen/codebase/outputs/V17/figures/shap_beeswarm.png` | not close — displayed Balance/SOFA directions partly agree, but Balance is not first and four required SOFA time positions are absent |
| Figure 12. SHAP waterfall plot for septic shock prediction used by the XGBoost model. | `codegen/codebase/outputs/V18/figures/shap_waterfall.png` | not close — baseline, output, contributions, time position, ordering, and residual display differ; the PNG conflicts with V18's table |
| Table A1. List of 78 predictor variables in alphabetical order. | `codegen/codebase/outputs/P5/feature_contract.parquet` | not assessable — a 78-entry Appendix-A1 contract exists, but no claim fragment verifies it row-for-row and the executed model retains only 67 of the 78 channels |

## Claim report paths

| C_i | Path |
| --- | --- |
| C1 | `report/claims/C1.md` |
| C2 | `report/claims/C2.md` |
| C3 | `report/claims/C3.md` |
| C4 | `report/claims/C4.md` |
| C5 | `report/claims/C5.md` |
| C6 | `report/claims/C6.md` |
| C7 | `report/claims/C7.md` |
| C8 | `report/claims/C8.md` |
| C9 | `report/claims/C9.md` |
| C10 | `report/claims/C10.md` |
| C11 | `report/claims/C11.md` |
| C12 | `report/claims/C12.md` |
| C13 | `report/claims/C13.md` |
| C14 | `report/claims/C14.md` |
| C15 | `report/claims/C15.md` |
| C16 | `report/claims/C16.md` |
| C17 | `report/claims/C17.md` |
| C18 | `report/claims/C18.md` |
| C19 | `report/claims/C19.md` |
| C20 | `report/claims/C20.md` |
| C21 | `report/claims/C21.md` |
| C22 | `report/claims/C22.md` |
| C23 | `report/claims/C23.md` |

## Node issues

| Node | Issues |
| --- | --- |
| D1 | none |
| P1 | [audit:001] Full local P1 preprocessing scanned the complete chart- and lab-event sources but crashed before producing its candidate cohort because the generated urine-output aggregate is object-typed and cannot be cumulatively summed.<br>[audit:001] The generated Sepsis-3 candidate construction does not implement the paper's required suspected-infection and clinical-feature definitions.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 1 corrected the candidate-cohort infection trigger, baseline-relative SOFA, and the paper-stated FiO2/GCS derivations.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 1 made urine and fluid aggregation numeric-safe across chunks and cumulative totals.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The paper says absent first values use a training-fold median but does not specify variable units or exact outlier rules.<br>[audit:002] P1 cannot materialize from the approved D1 source: its clinical-event reader omits the raw `value` column and then dereferences it.<br>[audit:002] P1's required 78-channel contract has an unreconcilable peak-inspiratory-pressure name mismatch.<br>[audit:002] P1 does not implement the paper-required fluid and vasopressor standardization; in particular, it would remove all mapped vasopressor exposure before septic-shock labeling.<br>[cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 2 repaired the P1 projected clinical-event contract and standardized intervention source mappings.<br>[audit:003] Complete local P1 execution failed before emitting the candidate cohort because required Appendix A1 channel total_co2 had no derived output.<br>[cohort_refine:003; codegen:001] Refinement round 3 restores the Appendix A1 total_co2 channel from MIMIC-IV's calculated blood-gas output.<br>[audit:004] The completed P1 artifact contains 23,728 candidate stays rather than the paper's 36,613 initial sepsis records; the resulting P2 cohort has mean SOFA 1.65, far below the paper's 5.5 sanity context.<br>[audit:004] P1 retains 15 variables above the paper's 80% missingness limit, including RASS and derived GCS; both have zero populated P5 source/output rows.<br>[replicate_agent] The completed candidate cohort contains 26,191 stays, below the paper's reported 35,215. Source parsing, RASS/GCS conversion, and SOFA/intervention logic were rechecked and yielded a complete non-null feature matrix; this observed source/cohort difference remains unresolved. |
| P2 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The paper mentions adult and insufficient-data exclusions but supplies no definition/count; its four enumerated exclusions sum exactly to the stated 1,398 removals.<br>[audit:004] P2 excludes 4,458 stays for low SOFA and emits 18,923 final stays; the paper reports only 503 SOFA exclusions and 35,215 final records after 1,398 total exclusions.<br>[replicate_agent] Raw exclusion predicates overlapped for seven stays, so the original count labels did not form a cohort-flow decomposition. Counts were repaired to sequential mutually exclusive removals without changing the excluded union or final cohort membership. |
| P3 | [audit:001] The mortality task matrix leaves leading missing values uninitialized instead of applying the paper-required training-fold baseline medians.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The paper specifies Stratified Group K-Fold and seed 42 but not the number of folds, threshold, static flattening order, or reconciliation of 78 predictors with excluded treatment-guided variables.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 1 completed the paper-required leading-value imputation in P3.<br>[audit:002] The shared static-task feature filter retains treatment-guided predictors that the paper and graph require P3/P4 to exclude.<br>[cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 2 replaced the incomplete prefix filter with canonical treatment-exclusion assertions for P3 and P4. |
| P4 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The paper calls the target remaining LOS but does not say whether LOS is ICU or hospital LOS, and says neither target units nor fold count.<br>[audit:002] P4 leaves leading missing values in its static LOS matrix instead of applying the paper-required training-fold-only baseline medians.<br>[cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 2 completed the P4 fold-local leading-value median artifact. |
| P5 | [audit:001] The septic-shock preprocessing cannot satisfy its required 78-channel (468 flattened-feature) contract from the generated feature set.<br>[audit:001] The generated future septic-shock label omits two of the paper's three phenotype conditions.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 1 completed the paper's three-condition, temporally aligned septic-shock label.<br>[cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 1 established the complete Appendix A1 P5 channel contract.<br>[audit:002] P5 flattens treatment-guided variables into all 468 shock inputs, rather than applying the graph's required final-model feature exclusion with only the documented balance inconsistency handled explicitly.<br>[audit:002] P5 has no fold-specific median completion for leading missing history values before producing its dynamic feature matrix.<br>[cohort_refine:002; cohort_refine:003; codegen:001] Refinement round 2 reconciled P5's Appendix A1 list with the paper's final treatment-feature exclusion and completed fold-local history imputation.<br>[audit:004] The P5 feature contract includes 67 channels, so its intended matrix width is 402, not the graph's stated 78 channels and 468 input variables; it also aborts because all fold-training medians for GCS/RASS are undefined.<br>[replicate_agent] The paper describes 78 Appendix A1 predictors (468 flattened values), while the graph/code's documented treatment-guided final-feature exclusion yields 67 predictors (402 flattened values). The executed artifact preserves the explicit final-model exclusion and balance exception rather than inventing missing predictors. |
| P6 | none |
| P7 | none |
| P8 | none |
| P9 | none |
| P10 | none |
| P11 | none |
| T1 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The paper reports final XGBoost parameters and GridSearchCV but not a grid, search scoring, or early stopping. |
| T2 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The LightGBM grid and objective details are omitted. |
| T3 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Transformer epochs, batch size, loss, positional encoding, and early stopping are omitted. |
| T4 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Random-Forest search grid/scoring are omitted.<br>[replicate_agent] The recovered T4 manifest was left in running state although five valid M4 Random Forest checkpoints existed. The completed staged record was reconstructed from those exact checkpoint bytes and separately republished by M4; no model was retrained. |
| T5 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] LSTM epochs, batch size, loss, and stopping are omitted.<br>[replicate_agent] The recovered T5 manifest was left in running state although five valid M5 LSTM checkpoints existed. The completed staged record was reconstructed from those exact checkpoint bytes and separately republished by M5; no model was retrained. |
| T6 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Logistic-Regresssion solver and search grid are omitted. |
| T7 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] LightGBM regression grid/objective are omitted. |
| T8 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] XGBoost regression grid/objective are omitted. |
| T9 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Regression LSTM loss, epochs, batch size, and stopping are omitted. |
| T10 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Random-Forest regression grid/scoring are omitted. |
| T11 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Lasso solver/grid/scoring are omitted. |
| T12 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Regression Transformer loss, epochs, batch size, and stopping are omitted. |
| T13 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Shock XGBoost grid/objective are omitted. |
| T14 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Shock LightGBM grid/objective are omitted. |
| T15 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Shock Random-Forest grid/scoring are omitted. |
| T16 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Shock Logistic solver/grid are omitted. |
| T17 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Shock LSTM loss, epochs, batch size, and stopping are omitted. |
| T18 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] Shock Transformer loss, epochs, batch size, and stopping are omitted. |
| M1 | none |
| M2 | none |
| M3 | none |
| M4 | none |
| M5 | none |
| M6 | none |
| M7 | none |
| M8 | none |
| M9 | none |
| M10 | none |
| M11 | none |
| M12 | none |
| M13 | none |
| M14 | none |
| M15 | none |
| M16 | none |
| M17 | none |
| M18 | none |
| V1 | none |
| V2 | none |
| V3 | none |
| V4 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The paper does not state a probability transformation or decision threshold for SOFA and NEWS used as score baselines. |
| V5 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The mortality confusion-matrix decision threshold is not reported. |
| V6 | none |
| V7 | none |
| V8 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The mortality SHAP waterfall patient-selection rule/identifier is omitted. |
| V9 | none |
| V10 | none |
| V11 | none |
| V12 | none |
| V13 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The LOS SHAP waterfall patient-selection rule/identifier is omitted. |
| V14 | none |
| V15 | none |
| V16 | none |
| V17 | none |
| V18 | [cohort_refine:001; cohort_refine:002; cohort_refine:003; codegen:001] The shock SHAP waterfall window-selection rule/identifier is omitted. |
| C1 | none |
| C2 | none |
| C3 | none |
| C4 | none |
| C5 | none |
| C6 | none |
| C7 | none |
| C8 | none |
| C9 | none |
| C10 | none |
| C11 | none |
| C12 | none |
| C13 | none |
| C14 | none |
| C15 | none |
| C16 | none |
| C17 | none |
| C18 | none |
| C19 | none |
| C20 | none |
| C21 | none |
| C22 | none |
| C23 | none |
