[Skip to main content](https://www.nature.com/articles/s41746-025-02276-9#content)

Thank you for visiting nature.com. You are using a browser version with limited support for CSS. To obtain
the best experience, we recommend you use a more up to date browser (or turn off compatibility mode in
Internet Explorer). In the meantime, to ensure continued support, we are displaying the site without styles
and JavaScript.

Prospective evaluation of speech as a digital biomarker for covert hepatic encephalopathy


[Download PDF](https://www.nature.com/articles/s41746-025-02276-9.pdf)

[Download PDF](https://www.nature.com/articles/s41746-025-02276-9.pdf)

## Abstract

Covert hepatic encephalopathy is a highly prevalent complication of liver failure or portosystemic shunting. However, the current diagnostic methods have not been widely adopted in routine clinical practice due to their time-consuming or technically complex nature. This study aimed to develop and evaluate a clinically feasible machine learning model capable of detecting covert hepatic encephalopathy using features extracted from sustained vowel phonation recordings. The XGBoost model achieved the highest AUROC of 81.20 (95% CI 73.03–89.73) and showed reasonable calibration across the full spectrum of predicted probabilities (Hosmer–Lemeshow _p_ = 0.66). The most influential features indicated that patients with covert hepatic encephalopathy tended to have reduced variation in volume, maintaining more constant and harsher vocal quality.

### Similar content being viewed by others

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-025-97878-4/MediaObjects/41598_2025_97878_Fig1_HTML.png)

### [Interpretable machine learning model for predicting post-hepatectomy liver failure in hepatocellular carcinoma](https://www.nature.com/articles/s41598-025-97878-4?fromPaywallRec=false)

ArticleOpen access03 May 2025

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-023-47012-z/MediaObjects/41598_2023_47012_Fig1_HTML.png)

### [Establishment and validation of a nomogram model for riskprediction of hepatic encephalopathy: a retrospective analysis](https://www.nature.com/articles/s41598-023-47012-z?fromPaywallRec=false)

ArticleOpen access09 November 2023

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-022-25900-0/MediaObjects/41598_2022_25900_Fig1_HTML.png)

### [Predicting graft failure in pediatric liver transplantation based on early biomarkers using machine learning models](https://www.nature.com/articles/s41598-022-25900-0?fromPaywallRec=false)

ArticleOpen access27 December 2022

## Introduction

Hepatic encephalopathy (HE) is a neuropsychiatric disorder linked to both acute and chronic liver failure and/or portosystemic shunting, caused by the accumulation of neurotoxic substances, such as ammonia, which the liver is unable to adequately remove[1](https://www.nature.com/articles/s41746-025-02276-9#ref-CR1 "Claeys, W. et al. The neurogliovascular unit in hepatic encephalopathy. JHEP Rep. 3, 100352                    https://doi.org/10.1016/j.jhepr.2021.100352                                     (2021)."). HE manifests as a spectrum of cognitive and motor disturbances, ranging from clinically undetectable to severely apparent. Diagnosing more advanced stages is generally straightforward, as these patients exhibit clear neurological symptoms such as disorientation, asterixis, or even coma. However, diagnosing subtler forms of HE, which are collectively referred to as “covert HE” (minimal HE and West Haven Grade 1 HE), is typically more intricate. While Grade 1 HE involves mild, yet detectable changes often noticed only by caregivers or physicians well-acquainted with the patient, minimal HE lacks obvious clinical signs and is identified only through specialized psychometric testing, such as the Psychometric Hepatic Encephalopathy Score (PHES), Stroop or Critical Flicker Frequency testing[2](https://www.nature.com/articles/s41746-025-02276-9#ref-CR2 "Vilstrup, H. et al. Hepatic encephalopathy in chronic liver disease: 2014 practice guideline by the European association for the study of the liver and the american association for the study of liver diseases. J. Hepatol. 60, 715–735 (2014).").

Covert HE is associated with a diminished quality of life, progression to overt HE, and thus worse overall survival[3](https://www.nature.com/articles/s41746-025-02276-9#ref-CR3 "Hartmann, I. J. C. et al. The prognostic significance of subclinical hepatic encephalopathy. Am. J. Gastroenterol. 95, 2029–2034 (2000)."), [4](https://www.nature.com/articles/s41746-025-02276-9#ref-CR4 "Ampuero, J. et al. Minimal hepatic encephalopathy identifies patients at risk of faster cirrhosis progression. J. Gastroenterol. Hepatol. 33, 718–725 (2018)."), [5](https://www.nature.com/articles/s41746-025-02276-9#ref-CR5 "Patidar, K. R. et al. Covert hepatic encephalopathy is independently associated with poor survival and increased risk of hospitalization. Am. J. Gastroenterol. 109, 1757–1763 (2014)."), [6](https://www.nature.com/articles/s41746-025-02276-9#ref-CR6 "Romero-Gomez, M., Boza, F., Garci'a-Valdecasas, M. S., Garci'a, E. & Aguilar-Reina, J. Subclinical hepatic encephalopathy predicts the development of overt hepatic encephalopathy. Am. J. Gastroenterol. 96, 2718–2723 (2001)."). A notable European study by Gairing et al. found that over one-third of patients with cirrhosis experience minimal HE, with a prevalence rate of 34.8% among the general cirrhotic population. However, the prevalence increases with the severity of liver failure, reaching 52.1% in patients classified as Child-Pugh Class C[7](https://www.nature.com/articles/s41746-025-02276-9#ref-CR7 "Gairing, S. J. et al. Prevalence of minimal hepatic encephalopathy in patients with liver cirrhosis: a multicenter study. Am. J. Gastroenterol. 118, 2191–2200 (2023).").

Despite the high prevalence of covert HE, it remains largely under-screened[8](https://www.nature.com/articles/s41746-025-02276-9#ref-CR8 "Bajaj, J. S., Etemadian, A., Hafeezullah, M. & Saeian, K. Testing for minimal hepatic encephalopathy in the United States: An AASLD survey [5]. Hepatology 45, 833−4                    https://doi.org/10.1002/hep.21515                                     (2007)."), hampering early intervention and improving outcomes[9](https://www.nature.com/articles/s41746-025-02276-9#ref-CR9 "Dhiman, R. K. et al. Comparative efficacy of treatment options for minimal hepatic encephalopathy: a systematic review and network meta-analysis. Clin. Gastroenterol. Hepatol. 18, 800–812.e25 (2020)."). This lack of screening is primarily due to the time-consuming or technically complex nature of the existing diagnostic methods. More importantly, there is no consensus on the recommended standard diagnostic approach. The European Association for the Study of the Liver (EASL) and the International Society for Hepatic Encephalopathy and Nitrogen Metabolism (ISHEN) offer conflicting recommendations for the diagnosis of minimal HE. While ISHEN discourages the use of multiple tests[10](https://www.nature.com/articles/s41746-025-02276-9#ref-CR10 "Bajaj, J. S. et al. Important unresolved questions in the management of hepatic encephalopathy: an ISHEN consensus. Am. J. Gastroenterol. 115, 989−1002                    https://doi.org/10.14309/ajg.0000000000000603                                     (2020)."), arguing that single methods are sufficient, EASL supports the use of more than one diagnostic test but acknowledges the limited data on how to effectively combine and interpret the results of these different tests[2](https://www.nature.com/articles/s41746-025-02276-9#ref-CR2 "Vilstrup, H. et al. Hepatic encephalopathy in chronic liver disease: 2014 practice guideline by the European association for the study of the liver and the american association for the study of liver diseases. J. Hepatol. 60, 715–735 (2014).").

Inspired by the success of machine learning in classifying patients with and without Parkinson’s disease based on speech patterns[11](https://www.nature.com/articles/s41746-025-02276-9#ref-CR11 "Ngo, Q. C. et al. Computerized analysis of speech and voice for Parkinson’s disease: a systematic review. Comput. Methods Prog. Biomed. 226, 107133                    https://doi.org/10.1016/j.cmpb.2022.107133                                     (2022)."), we explored the adaptation of a similar approach for detecting covert HE, given that patients with overt HE often exhibit noticeable speech alterations. In this study, we present a proof-of-concept for a novel, prospective diagnostic method for covert HE based on sustained-vowel voice analysis, complemented by an explainable machine learning approach that elucidates the key factors driving the model’s predictions and addresses the traditional ‘black box’ nature of AI.

## Results

### Patients’ characteristics

Thirty-six cirrhotic patients had covert HE (20 patients had minimal HE diagnosed by a pathological result on EncephalApp\_Stroop and 16 patients had Grade 1 HE) while eight cirrhotic patients did not present signs of covert HE. None of the patients had any history of TIPS placement.

In the covert HE cohort ( _n_ = 36), there were 21 male patients (58%) and the median age was 58 years (IQR 49−70). Alcohol-related liver disease was the most common underlying disease. The median Child-Pugh score was 7 (IQR 5−10), and the median MELD score was 12 (IQR 7-19). The clinical and laboratory characteristics are presented in Table [1](https://www.nature.com/articles/s41746-025-02276-9#Tab1).

**Table 1 Overall characteristics of the two cohorts (with and without covert HE)**

[Full size table](https://www.nature.com/articles/s41746-025-02276-9/tables/1)

The control group ( _n_ = 57) comprised individuals without evidence of HE. This group included patients with liver cirrhosis but no signs of HE and a normal EncephalApp\_Stroop result ( _n_ = 8/57, 14%), as well as individuals without advanced liver disease or healthy volunteers ( _n_ = 49/57, 86%). The overall distribution of patients’ is presented in Fig. [1](https://www.nature.com/articles/s41746-025-02276-9#Fig1). There was no difference in age, gender, or education among the cohorts ( _p_ = 0.5, _p_ = 0.3, and _p_ = 0.9, respectively).

**Fig. 1: Distribution of all enrolled participants into the study cohorts.**

![Fig. 1: Distribution of all enrolled participants into the study cohorts.](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41746-025-02276-9/MediaObjects/41746_2025_2276_Fig1_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41746-025-02276-9/figures/1)

Flowchart of the study population showing the distribution of participants across diagnostic subgroups.

### Model training and evaluation

We trained and evaluated models for the diagnosis of covert HE across 13 distinct tasks, each involving different combinations of “a:” and “e:” on low and high volume. In overall, the best discriminatory performance was achieved by XGBoost using a combination of recordings of both vowels “a:” (low volume + high volume) and “e:” (high volume) (Table [2](https://www.nature.com/articles/s41746-025-02276-9#Tab2)).

**Table 2 Performance comparison of machine learning classifiers**

[Full size table](https://www.nature.com/articles/s41746-025-02276-9/tables/2)

### XGBoost performance

The XGBoost model achieved an AUROC of 81.20 (95% CI 73.03–89.73, SD 4.20) and demonstrated both plateaued learning curve and reasonable calibration across the full range of predicted probabilities ( _p_ = 0.66; Table [2](https://www.nature.com/articles/s41746-025-02276-9#Tab2) and Fig. [2](https://www.nature.com/articles/s41746-025-02276-9#Fig2)).

**Fig. 2: Performance evaluation of the final XGBoost model.**

![Fig. 2: Performance evaluation of the final XGBoost model.](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41746-025-02276-9/MediaObjects/41746_2025_2276_Fig2_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41746-025-02276-9/figures/2)

**a** Receiver operating characteristic (ROC) curve demonstrating discriminative ability compared with the random classifier reference line. **b** Calibration curve with 80% and 95% confidence bands demonstrating agreement between predicted and observed probabilities. **c** Learning curve illustrating training and validation AUCs across increasing training set sizes.

The SHAP summary plot identified the features with the greatest impact on the output of the model, as indicated by the highest mean SHAP values: (1) zero-crossing rate, (2) magnitude spectrum Q2, (3) magnitude spectrum p1, and (4) magnitude spectrum Q1 (Fig. [3](https://www.nature.com/articles/s41746-025-02276-9#Fig3)).

**Fig. 3: Summary plot of the final XGBoost model.**

![Fig. 3: Summary plot of the final XGBoost model.](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41746-025-02276-9/MediaObjects/41746_2025_2276_Fig3_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41746-025-02276-9/figures/3)

Summary plot showing the most influential acoustic features contributing to the model’s predictions.

The dependence plots (Fig. [4](https://www.nature.com/articles/s41746-025-02276-9#Fig4)) show that that a high zero crossing rate (harsh sound) indicates an increased likelihood of covert HE. Conversely, a mellow sound with a low zero crossing rate suggests a decreased likelihood of covert HE. The other most important features were the first percentile and first and second quartile of the magnitude spectrum. The high magnitude in the first percentile suggests that patients with covert HE tend to have a higher volume of very quiet sounds than controls. This means that they struggle to reduce their voice energy when needed—indicating an inability to speak quietly when appropriate. On the other hand, the low magnitude in the first and second quartiles suggests that patients with covert HE might also have trouble increasing the volume adequately when speaking louder is necessary. In other words, people with covert HE tend to struggle to naturally vary how loud they speak, keeping their voice at a more constant volume regardless of the situation. Although other features were present, they did not significantly influence model predictions (low mean SHAP values).

**Fig. 4: Dependence plot of the final XGBoost model.**

![Fig. 4: Dependence plot of the final XGBoost model.](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41746-025-02276-9/MediaObjects/41746_2025_2276_Fig4_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41746-025-02276-9/figures/4)

Dependence plot illustrating how variations in a selected acoustic feature influence the model’s predicted probability of covert hepatic encephalopathy.

Only 8 cases (8.6%) reported having a B2 or higher level of proficiency in a foreign language (three in the covert HE group and five in the no HE group). One of the eight “multilingual” cases was misclassified, leading to an accuracy of 87.5. The misclassified case belonged to the “no HE cohort”.

### Sensitivity analyses

Finally, we performed sensitivity analyses, calculating separate AUROC curves for two other scenarios: (1) cirrhotic patients only (cirrhosis with covert HE vs cirrhosis without HE), and (2) covert HE vs non-cirrhotic controls, to illustrate how the model’s discriminatory performance varies by control group composition. No significant departure from the primary analysis was observed, as the AUROCs for the cirrhotics-only and non-cirrhotic-only control group comparisons were 87.04 (95% CI 78.19–94.12) and 79.75 (95% CI 71.38–88.00), respectively.

## Discussion

Covert HE is a common yet often overlooked complication of liver cirrhosis, with a prevalence that increases as liver failure progresses. Despite the significant burden it imposes, covert HE remains underdiagnosed and undertreated, largely owing to the limitations of current diagnostic methods[8](https://www.nature.com/articles/s41746-025-02276-9#ref-CR8 "Bajaj, J. S., Etemadian, A., Hafeezullah, M. & Saeian, K. Testing for minimal hepatic encephalopathy in the United States: An AASLD survey [5]. Hepatology 45, 833−4                    https://doi.org/10.1002/hep.21515                                     (2007)."). This underdiagnosis not only prevents timely pharmacological intervention[9](https://www.nature.com/articles/s41746-025-02276-9#ref-CR9 "Dhiman, R. K. et al. Comparative efficacy of treatment options for minimal hepatic encephalopathy: a systematic review and network meta-analysis. Clin. Gastroenterol. Hepatol. 18, 800–812.e25 (2020).") but also leaves patients vulnerable to the risks associated with impaired decision-making in high-risk situations. Furthermore, the need for improved diagnostic tools and a more proactive screening approach is now more critical than ever, particularly because of the rising proportion of patients receiving transjugular intrahepatic portosystemic shunts. Such a model could therefore be used also in the selection process for TIPS and for monitoring patients after the procedure.

In this study, we present a detailed description of the development of a proof-of-concept machine learning model that identifies patients with covert HE based on speech analysis[12](https://www.nature.com/articles/s41746-025-02276-9#ref-CR12 "Gazda, J. et al. OS-036-YI Diagnostic potential of speech artificial intelligence analysis in minimal hepatic encephalopathy. J. Hepatol. 80, S29 (2024).").

Our study was conducted in a specific population of patients with liver cirrhosis, characterized by a relatively high prevalence of covert hepatic encephalopathy. As noted earlier, part of the study took place during the COVID-19 restrictions, when hospital visits were in Slovakia limited to severely ill patients only. Moreover, we used the EncephalApp\_Stroop test to diagnose minimal HE, which has been reported to have the highest sensitivity among established diagnostic tools[13](https://www.nature.com/articles/s41746-025-02276-9#ref-CR13 "Duarte-Rojo, A. et al. Diagnosis of covert hepatic encephalopathy: a multi-center study testing the utility of single versus combined testing. Metab Brain Dis 34, 289–295 (2019)."). Both factors may have contributed to the higher observed incidence, which, however, remained at the upper end of the range reported in the literature[14](https://www.nature.com/articles/s41746-025-02276-9#ref-CR14 "Lv, X. H., Lu, Q., Deng, K., Yang, J. L. & Yang, L. Prevalence and characteristics of covert/minimal hepatic encephalopathy in patients with liver cirrhosis: a systematic review and meta-analysis. Am. J. Gastroenterol. 119, 690–699 (2024)."). We believe that this should not have a significant impact on the overall conclusions of the study. In addition, we included individuals without advanced liver disease. The inclusion of noncirrhotic controls aligns with foundational research that led to the development of currently accepted diagnostic tools such as the PHES and the EncephalApp\_Stroop test[8](https://www.nature.com/articles/s41746-025-02276-9#ref-CR8 "Bajaj, J. S., Etemadian, A., Hafeezullah, M. & Saeian, K. Testing for minimal hepatic encephalopathy in the United States: An AASLD survey [5]. Hepatology 45, 833−4                    https://doi.org/10.1002/hep.21515                                     (2007)."), [15](https://www.nature.com/articles/s41746-025-02276-9#ref-CR15 "Weissenborn, K., Ennen, J. C., Schomerus, H., Rückert, N. & Hecker, H. Neuropsychological characterization of hepatic encephalopathy. J. Hepatol. 34, 768–773 (2001).").

XGBoost model demonstrated the best discriminatory characteristics (AUROC 81.20 ± 4.2 (95% CI: 73.03–89.73)) while maintaining calibration with good 95% CI across the whole spectrum of probabilities ( _p_ = 0.66). The proposed model is potentially easy to use, requiring only a smartphone/computer application and no more than 15 s of speech recording per patient. This is in stark contrast to the currently employed methods, which are both technically demanding and time-consuming[16](https://www.nature.com/articles/s41746-025-02276-9#ref-CR16 "Karanfilian, B. V., Park, T., Senatore, F. & Rustgi, V. K. Minimal hepatic encephalopathy. Clin. Liver Dis. 24, 209–218 (2020).").

An interesting comparison can be made with a recent study by Bloom et al. who examined running speech features in a similarly large cohort of minimal HE patients ( _n_ = 40)[17](https://www.nature.com/articles/s41746-025-02276-9#ref-CR17 "Bloom, P. P. et al. HEAR-MHE study: Automated speech analysis identifies minimal hepatic encephalopathy and may predict future overt hepatic encephalopathy. Hepatology 81, 1740−1752 (2024)."). This study observed that a slower speech rate is commonly associated with HE and used this feature alongside acoustic variables different from ours (such as mel-frequency cepstrum coefficients skewness 22 and jitter local absolute). The model by Bloom et al. achieved an AUROC of 0.76 (95% CI 0.67—0.84), although calibration across the full probability spectrum (0%–100%) was not reported, limiting insights into the model’s reliability at extreme probabilities. Notably, the authors enhanced their model by incorporating age and MELD-Na, which raised the AUROC to 0.82 (95% CI 0.74–0.90), close to our model’s performance.

To remove the skepticism behind artificial intelligence, still largely present among clinicians, we present dedicated research explaining how the model arrives at outcomes. We believe that removing the black box of the model’s decisions will improve the acceptance of the model in future research and clinical practice. Indeed, we only confirmed the changes, that an experienced clinician would expect in the speech of patients with covert HE. The most important group of features behind the machine learning model decisions was that people with covert HE tend to struggle to naturally vary how loud they speak, keeping their voice at a more constant volume and harsh regardless of the situation. We also acknowledge that the best-performing model was based on the combination of “a:” (low and high volume) and “e:” (high volume). This could be attributed to two key factors. First, the vowel “a” lies at the edge of the Hellwag triangle, unlike “e”, and its articulation requires a more complex positioning of the vocal tract[18](https://www.nature.com/articles/s41746-025-02276-9#ref-CR18 "Redford, M. A. The Handbook of Speech Production. The Handbook of Speech Production Illustrated edition, Vol. 616 (John Wiley & Sons, 2015)."). This increased articulatory demand may expose subtle neuromotor deficits, making it more informative for the detection of covert HE. Second, the model appears to capture volume-related variability sufficiently through the soft and loud recordings of “a:”, rendering the additional soft “e:” redundant and less informative.

Our study has few limitations. First, the speech characteristics can vary significantly across languages. To mitigate this, we focused on basic speech elements, such as sustained vowels, which tend to remain relatively stable across different linguistic contexts. Second, the small sample size, namely cirrhotic patients without covert HE, and a lack of true external validation. To mitigate the impact of the small sample size, we employed outcome-stratified nested cross-validation with out-of-fold predictions—one of the most robust validation strategies available—to reduce the risk of overfitting and provide a nearly unbiased estimate of model performance. Nevertheless, the first two limitations reduce the generalizability of our findings; accordingly, the results should be viewed as hypothesis-generating, highlighting the need for validation in larger and multilingual cohorts. Third, the diagnosis of minimal HE relied solely on the EncephalApp\_Stroop test. Although this tool has been validated, it may not detect all cases of minimal HE, potentially leading to misclassification which might have propagated into the presented model.

In conclusion, this study presents the potential of speech analysis—specifically sustained vowel phonation—combined with an XGBoost classification model as a non-invasive and easily obtainable digital biomarker for the detection of covert hepatic encephalopathy. However, further evaluation in larger and multilingual cohorts is required before any real-world clinical adoption.

## Methods

### Design

This prospective cross-sectional observational case-control study was conducted at a tertiary liver care center (2nd Department of Internal Medicine, Pavol Jozef Safarik University and L Pasteur University Hospital in Kosice, Slovakia). The local ethics committee approved the study protocol on 14th November 2018 (ethics committee no. 117/EK/18). All patients provided informed consent to participate in the study. This study adheres to the TRIPOD guidelines[19](https://www.nature.com/articles/s41746-025-02276-9#ref-CR19 "Collins, G. S., Reitsma, J. B., Altman, D. G. & Moons, K. G. M. Transparent reporting of a multivariable prediction model for individual prognosis or diagnosis (TRIPOD): the TRIPOD statement. Ann. Intern. Med. 131, 211–219 (2015).").

### Definitions

The diagnosis of cirrhosis was established prior to the study inclusion and was based on a combination of laboratory and imaging findings—including ultrasonography, elastography, and endoscopy—which were consistent with liver cirrhosis. The diagnosis of covert HE was established based on the presence of either Minimal or Grade 1 HE. Minimal HE was diagnosed following EASL and ISHEN recommendations[2](https://www.nature.com/articles/s41746-025-02276-9#ref-CR2 "Vilstrup, H. et al. Hepatic encephalopathy in chronic liver disease: 2014 practice guideline by the European association for the study of the liver and the american association for the study of liver diseases. J. Hepatol. 60, 715–735 (2014)."), [10](https://www.nature.com/articles/s41746-025-02276-9#ref-CR10 "Bajaj, J. S. et al. Important unresolved questions in the management of hepatic encephalopathy: an ISHEN consensus. Am. J. Gastroenterol. 115, 989−1002                    https://doi.org/10.14309/ajg.0000000000000603                                     (2020)."), using a pathological result on a validated EncephalApp\_Stroop test as the defining criterion (total off-time ≥ 125.84 s as reported by Bajaj et al.)[20](https://www.nature.com/articles/s41746-025-02276-9#ref-CR20 "Bajaj, J. S. et al. The stroop smartphone application is a short and valid method to screen for minimal hepatic encephalopathy. Hepatology 58, 1122–1132 (2013)."). Grade 1 HE was diagnosed when one or more of the following signs were present: trivial lack of awareness, euphoria or anxiety, shortened attention span, impairment of addition or subtraction, or altered sleep–wake rhythm)[2](https://www.nature.com/articles/s41746-025-02276-9#ref-CR2 "Vilstrup, H. et al. Hepatic encephalopathy in chronic liver disease: 2014 practice guideline by the European association for the study of the liver and the american association for the study of liver diseases. J. Hepatol. 60, 715–735 (2014)."). The assessment was jointly performed by a junior specialist (JG) and a consultant (MJ), with 8 and 16 years of clinical experience, respectively, both specializing in liver diseases. A mutual agreement was reached in all patients.

### Patients

We included patients with known liver cirrhosis scheduled for examination at the outpatient liver clinic. Furthermore, individuals without advanced liver disease and without hepatic encephalopathy. The latter included healthy volunteers—primarily hospital employees and their family members or friends—as well as individuals diagnosed with metabolic dysfunction-associated steatotic liver disease (MASLD) without signs of advanced fibrosis (as evidenced by transient elastography/Fib-4), or with benign liver hemangioma. This approach is conceptually aligned with prior standardization studies of diagnostic tools for covert HE—instruments such as PHES[21](https://www.nature.com/articles/s41746-025-02276-9#ref-CR21 "Amodio, P. et al. Detection of minimal hepatic encephalopathy: normalization and optimization of the psychometric hepatic encephalopathy score. A neuropsychological and quantified EEG study. J Hepatol 49, 346–353 (2008).") and the EncephalApp Stroop test[20](https://www.nature.com/articles/s41746-025-02276-9#ref-CR20 "Bajaj, J. S. et al. The stroop smartphone application is a short and valid method to screen for minimal hepatic encephalopathy. Hepatology 58, 1122–1132 (2013).") similarly incorporated healthy subjects to establish normative performance boundaries before evaluating diagnostic validity within cirrhotic cohorts.

Patients were enrolled between June 2019 and February 2025, with intermittent pauses during the COVID-19 lockdowns. Individuals younger than 18 years or older than 80 years, as well as those unwilling to participate, were excluded. To minimize potential confounding factors affecting voice characteristics, additional predefined exclusion criteria were applied: treatment with any psychiatric or psychoactive medication, the presence of active infections or intoxications; any neurological or psychiatric disorder (including overt hepatic encephalopathy, Wernicke encephalopathy, or Korsakoff syndrome); metabolic conditions such as diabetes with acute or chronic complications, acute kidney injury, or chronic kidney disease; respiratory insufficiency; and malignant diseases.

### Voice recordings

All voice recordings were performed in Slovak and collected under standardized acoustic conditions to minimize environmental variability. Recordings took place in the same quiet room for all participants, ensuring consistent background noise levels. Audio acquisition was carried out using a Blue Yeti Aurora external microphone, set to 16 kHz sampling rate and 16-bit PCM encoding, connected to a desktop computer running Audacity software (version 2.3, Muse Group). The microphone gain was adjusted before each session to avoid clipping, and no hardware-level noise reduction or real-time denoising was applied.

Participants were seated ~25 cm from the microphone and instructed to begin sustained vowel phonation immediately after an optical signal indicated the start of recording, continuing for 5 s until a second signal marked its termination. This protocol ensured consistent capture of the onset, steady-state, and offset phases of phonation (fade-in and fade-out). The procedure was repeated for four tasks—sustained /aː/ (as in _“father”_) and /eː/ (as in _“excellent”_), each produced at low and high volume. If any recording was interrupted, incomplete, or exhibited irregular phonation, it was repeated to maintain consistency and data quality.

Sustained vowel phonation was selected because it offers the linguistically most neutral and standardized speech unit, decreasing the cross-speaker and cross-language variability that typically affects running speech[22](https://www.nature.com/articles/s41746-025-02276-9#ref-CR22 "Gerratt, B. R., Kreiman, J. & Garellek, M. Comparing measures of voice quality from sustained phonation and continuous speech. J. Speech Lang. Hearing Res. 59, 994–1001 (2016)."). This methodological choice aligns with prior voice-based digital biomarker studies in Parkinson’s disease[23](https://www.nature.com/articles/s41746-025-02276-9#ref-CR23 "Tsanas, A., Little, M. A., McSharry, P. E., Spielman, J. & Ramig, L. O. Novel speech signal processing algorithms for high-accuracy classification of Parkinsons disease. IEEE Trans. Biomed. Eng 59, 1264–1271 (2012)."), amyotrophic lateral sclerosis[24](https://www.nature.com/articles/s41746-025-02276-9#ref-CR24 "Vashkevich, M. & Rushkevich, Y. Classification of ALS patients based on acoustic analysis of sustained vowel phonations. Biomed. Signal Process Control 65, 102350 (2021)."), and other neurological and speech-related conditions[25](https://www.nature.com/articles/s41746-025-02276-9#ref-CR25 "Sapir, S., Ramig, L. O., Spielman, J. L. & Fox, C. Formant centralization ratio: a proposal for a new acoustic measure of dysarthric speech. J. Speech Lang. Hearing Res. 53, 114–125 (2010)."), [26](https://www.nature.com/articles/s41746-025-02276-9#ref-CR26 "Gómez-Vilda, P. et al. Assessing laryngeal neuromotor activity from phonation. Int. J. Neural Syst. 35, 2550029 (2025)."). For these reasons—and to facilitate future external validation in multilingual cohorts—we restricted the present analysis to sustained vowel phonation.

### Audio preprocessing

All recordings underwent a standardized preprocessing pipeline prior to feature extraction. No additional denoising or filtering was applied in order to preserve the original acoustic characteristics of the signal.

### Features extraction

Following preprocessing, we extracted 28 acoustic features commonly used in pathological speech and neurological voice analysis[11](https://www.nature.com/articles/s41746-025-02276-9#ref-CR11 "Ngo, Q. C. et al. Computerized analysis of speech and voice for Parkinson’s disease: a systematic review. Comput. Methods Prog. Biomed. 226, 107133                    https://doi.org/10.1016/j.cmpb.2022.107133                                     (2022)."), [27](https://www.nature.com/articles/s41746-025-02276-9#ref-CR27 "Mekyska, J. et al. Robust and complex approach of pathological speech signal analysis. Neurocomputing 167, 94–111 (2015)."). These included measures of phonatory stability, amplitude variation, spectral shape, and harmonic structure. Feature computation was performed using the Librosa (v0.10.1) and Surfboard (v0.2.0) Python libraries.

The following features were extracted: Log Mel Spectrogram, Morlet Continuous Wavelet Transform, Fundamental Frequency Statistics, Loudness, Root Mean Square Energy, Fundamental Frequency Contour, Formants, Linear Prediction Coefficients, Detrended Fluctuation Analysis, Harmonics-to-Noise Ratio, Shimmer (Amplitude Perturbation), Jitter (Frequency Perturbation), Pitch Period Entropy, Logarithmic Energy, Intensity, Zero Crossing Rate, Mel-Frequency Cepstral Coefficients, Chroma Short-Time Fourier Transform, Chroma Constant-Q Transform, Chroma Energy Normalized Statistics, Formants Sliding Window Analysis, Magnitude Spectrum, Bark Scale Spectrogram, Spectral Slope, Spectral Flux, Spectral Centroid, Spectral Spread, Linear Spectral Frequencies. Zero Crossing Rate is scalar value and can be directly used as an input to a classifier. However, features like the Magnitude Spectrum, Log Mel Spectrogram and others which are extracted as vectors, require additional processing. For these vector-based features, we calculate statistical functionals, such as the mean, max, min, standard deviation, first quartile (Q1), second quartile (median), third quartile (Q3), first percentile (P1), 99th percentile (99 P), and interquartile ranges (Q2-Q1, Q3-Q1, Q3-Q2).

### Model training

To evaluate classification performance across algorithmic families, we trained four machine-learning models: Elastic net-regularized logistic regression, support vector machine, random forest, and XGBoost.

Hyperparameter tuning was performed using an outcome-stratified nested cross-validation with out-of-fold predictions to ensure an unbiased performance estimate. This method consists of two nested loops: (1) an outer loop and (2) an inner loop. The outer loop first partitions the entire dataset into 10 folds. In each iteration, one of these 10 folds is designated as an independent, untouched outer validation set. The remaining nine folds serve as the training set for hyperparameter tuning. This process guarantees that every data sample is used for the final validation exactly and only once and remains completely separate from the model training process in that specific iteration. Within the training set of each outer loop, an inner loop was used to determine the optimal hyperparameters. This loop performs a 5-fold cross-validation, systematically evaluating different hyperparameter combinations. The combination that achieved the best performance on the inner validation folds was selected as the optimal configuration. This optimal hyperparameter configuration was then used to train the final model on the entire training set of the outer loop. The performance of the trained model was then evaluated on the untouched outer validation set. The entire process was repeated 10 times, with each of the original 10 folds serving as the outer validation set (i.e. multiple external-like validations). The final performance metrics were calculated by averaging the results from all ten outer validation folds. This nested approach provides a robust and less optimistic estimate of the true generalization error of the model, mimicking the evaluation on a completely new, unseen dataset[28](https://www.nature.com/articles/s41746-025-02276-9#ref-CR28 "Varma, S. & Simon, R. Bias in error estimation when using cross-validation for model selection. BMC Bioinform. 7, 91 (2006).").

The following grid search strategy over specified hyperparameters was applied in inner 5-fold CV: (1) for XGBoost—subsample \[0.5, 0.75, 1\], num\_parallel\_tree \[100\], max\_depth \[3,6,9\], learning\_rate \[0.05, 0.1, 0.2\], min\_child\_weight \[1, 10, 100\], (2) for logistic regression—solver \[saga\], penalty \[elasticnet\], l1\_ratio \[0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.9\], C \[0.05, 0.1, 0.15, 0.25, 0.5\], class\_weight \[none, balanced\], tol \[1e–5\], (3) for SVM—kernel \[rbf\], C \[0.01, 0.1, 1, 10, 100\], gamma \[scale, 1, 0.1, 0.01, 0.001, 0.0001\], (4) for random forest—n\_estimators \[100, 200, 300\], max\_depth \[10,15,20\], min\_samples\_split \[10,20,50\], min\_samples\_leaf \[2,5,10\].

### Model evaluation

Model discrimination is represented by the area under the receiver operating characteristic curve (AUROC) with a standard deviation (SD) and 95% confidence interval (95% CI), estimated using bootstrap resampling on aggregated CV estimates with 200 replicates. Model calibration is shown with calibration belts (GivitiR), and miscalibration significance was evaluated using the Hosmer-Lemeshow test.

### Explainability

To interpret the predictions of the model with the best discriminatory and calibration characteristics, SHAP (SHapley Additive exPlanations) values were used, quantifying the contribution of each feature to individual predictions (higher SHAP values mean a greater impact)[29](https://www.nature.com/articles/s41746-025-02276-9#ref-CR29 "Lundberg, S. M. et al. From local explanations to global understanding with explainable AI for trees. Nat. Mach. Intell. 2, 56–67 (2020)."). A summary and dependence plots present the distribution of SHAP values for each feature across all samples, emphasizing the features with the most significant influence. Machine learning was carried out in Python 3.9.18, using scikit-learn package 1.3.2 and XGBoost package 2.0.2.

### Descriptive statistical analyses

Descriptive statistical analyses were performed out using RStudio software (version 1.2.1335). Continuous variables are presented as median and interquartile range (IQR). Categorical variables are presented as absolute counts and percentages (%). There were no missing values in the analyzed variables. The significance of distribution differences in continuous and categorical variables was examined using the Kruskall–Wallis and ChiSquare tests. All tests were performed at a significance level of _p_ ≤ 0.05.

### Weights availability

XGBoost weights are available on GitHub: [https://github.com/matthires/covert\_hepatic\_encephalopathy](https://github.com/matthires/covert_hepatic_encephalopathy).

## Data availability

The data supporting the findings of this study are available from the first or corresponding author upon request and are subject to approval by the institutional ethical committee. The model weights are publicly available on the project's GitHub page.

## Code availability

The Python code is available from the first or corresponding author upon request.

## References

01. Claeys, W. et al. The neurogliovascular unit in hepatic encephalopathy. _JHEP Rep_. **3**, 100352 [https://doi.org/10.1016/j.jhepr.2021.100352](https://doi.org/10.1016/j.jhepr.2021.100352) (2021).

02. Vilstrup, H. et al. Hepatic encephalopathy in chronic liver disease: 2014 practice guideline by the European association for the study of the liver and the american association for the study of liver diseases. _J. Hepatol._ **60**, 715–735 (2014).

    [Article](https://doi.org/10.1002%2Fhep.27210) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Hepatic%20encephalopathy%20in%20chronic%20liver%20disease%3A%202014%20practice%20guideline%20by%20the%20European%20association%20for%20the%20study%20of%20the%20liver%20and%20the%20american%20association%20for%20the%20study%20of%20liver%20diseases&journal=J.%20Hepatol.&doi=10.1002%2Fhep.27210&volume=60&pages=715-735&publication_year=2014&author=Vilstrup%2CH)

03. Hartmann, I. J. C. et al. The prognostic significance of subclinical hepatic encephalopathy. _Am. J. Gastroenterol._ **95**, 2029–2034 (2000).

    [Article](https://doi.org/10.1111%2Fj.1572-0241.2000.02265.x) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DC%2BD3cvhs1aqsQ%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10950053) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20prognostic%20significance%20of%20subclinical%20hepatic%20encephalopathy&journal=Am.%20J.%20Gastroenterol.&doi=10.1111%2Fj.1572-0241.2000.02265.x&volume=95&pages=2029-2034&publication_year=2000&author=Hartmann%2CIJC)

04. Ampuero, J. et al. Minimal hepatic encephalopathy identifies patients at risk of faster cirrhosis progression. _J. Gastroenterol. Hepatol._ **33**, 718–725 (2018).

    [Article](https://doi.org/10.1111%2Fjgh.13917) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=28768371) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Minimal%20hepatic%20encephalopathy%20identifies%20patients%20at%20risk%20of%20faster%20cirrhosis%20progression&journal=J.%20Gastroenterol.%20Hepatol.&doi=10.1111%2Fjgh.13917&volume=33&pages=718-725&publication_year=2018&author=Ampuero%2CJ)

05. Patidar, K. R. et al. Covert hepatic encephalopathy is independently associated with poor survival and increased risk of hospitalization. _Am. J. Gastroenterol._ **109**, 1757–1763 (2014).

    [Article](https://doi.org/10.1038%2Fajg.2014.264) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=25178701) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC4321782) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Covert%20hepatic%20encephalopathy%20is%20independently%20associated%20with%20poor%20survival%20and%20increased%20risk%20of%20hospitalization&journal=Am.%20J.%20Gastroenterol.&doi=10.1038%2Fajg.2014.264&volume=109&pages=1757-1763&publication_year=2014&author=Patidar%2CKR)

06. Romero-Gomez, M., Boza, F., Garci'a-Valdecasas, M. S., Garci'a, E. & Aguilar-Reina, J. Subclinical hepatic encephalopathy predicts the development of overt hepatic encephalopathy. _Am. J. Gastroenterol._ **96**, 2718–2723 (2001).

    [Article](https://doi.org/10.1111%2Fj.1572-0241.2001.04130.x) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DC%2BD3MritFertQ%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=11569701) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Subclinical%20hepatic%20encephalopathy%20predicts%20the%20development%20of%20overt%20hepatic%20encephalopathy&journal=Am.%20J.%20Gastroenterol.&doi=10.1111%2Fj.1572-0241.2001.04130.x&volume=96&pages=2718-2723&publication_year=2001&author=Romero-Gomez%2CM&author=Boza%2CF&author=Garci%27a-Valdecasas%2CMS&author=Garci%27a%2CE&author=Aguilar-Reina%2CJ)

07. Gairing, S. J. et al. Prevalence of minimal hepatic encephalopathy in patients with liver cirrhosis: a multicenter study. _Am. J. Gastroenterol._ **118**, 2191–2200 (2023).

    [Article](https://doi.org/10.14309%2Fajg.0000000000002251) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3sXisVyjsbnJ) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=36940426) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Prevalence%20of%20minimal%20hepatic%20encephalopathy%20in%20patients%20with%20liver%20cirrhosis%3A%20a%20multicenter%20study&journal=Am.%20J.%20Gastroenterol.&doi=10.14309%2Fajg.0000000000002251&volume=118&pages=2191-2200&publication_year=2023&author=Gairing%2CSJ)

08. Bajaj, J. S., Etemadian, A., Hafeezullah, M. & Saeian, K. Testing for minimal hepatic encephalopathy in the United States: An AASLD survey \[5\]. _Hepatology_ **45**, 833−4 [https://doi.org/10.1002/hep.21515](https://doi.org/10.1002/hep.21515) (2007).

09. Dhiman, R. K. et al. Comparative efficacy of treatment options for minimal hepatic encephalopathy: a systematic review and network meta-analysis. _Clin. Gastroenterol. Hepatol._ **18**, 800–812.e25 (2020).

    [Article](https://doi.org/10.1016%2Fj.cgh.2019.08.047) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC1MXitFKitLfL) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=31476436) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Comparative%20efficacy%20of%20treatment%20options%20for%20minimal%20hepatic%20encephalopathy%3A%20a%20systematic%20review%20and%20network%20meta-analysis&journal=Clin.%20Gastroenterol.%20Hepatol.&doi=10.1016%2Fj.cgh.2019.08.047&volume=18&pages=800-812.e25&publication_year=2020&author=Dhiman%2CRK)

10. Bajaj, J. S. et al. Important unresolved questions in the management of hepatic encephalopathy: an ISHEN consensus. _Am. J. Gastroenterol_. **115**, 989−1002 [https://doi.org/10.14309/ajg.0000000000000603](https://doi.org/10.14309/ajg.0000000000000603) (2020).

11. Ngo, Q. C. et al. Computerized analysis of speech and voice for Parkinson’s disease: a systematic review. _Comput. Methods Prog_ _. Biomed_. **226**, 107133 [https://doi.org/10.1016/j.cmpb.2022.107133](https://doi.org/10.1016/j.cmpb.2022.107133) (2022).

12. Gazda, J. et al. OS-036-YI Diagnostic potential of speech artificial intelligence analysis in minimal hepatic encephalopathy. _J. Hepatol._ **80**, S29 (2024).

    [Article](https://doi.org/10.1016%2FS0168-8278%2824%2900477-X) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=OS-036-YI%20Diagnostic%20potential%20of%20speech%20artificial%20intelligence%20analysis%20in%20minimal%20hepatic%20encephalopathy&journal=J.%20Hepatol.&doi=10.1016%2FS0168-8278%2824%2900477-X&volume=80&publication_year=2024&author=Gazda%2CJ)

13. Duarte-Rojo, A. et al. Diagnosis of covert hepatic encephalopathy: a multi-center study testing the utility of single versus combined testing. _Metab Brain Dis_ **34**, 289–295 (2019).

    [Article](https://link.springer.com/doi/10.1007/s11011-018-0350-z) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=30506333) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Diagnosis%20of%20covert%20hepatic%20encephalopathy%3A%20a%20multi-center%20study%20testing%20the%20utility%20of%20single%20versus%20combined%20testing&journal=Metab%20Brain%20Dis&doi=10.1007%2Fs11011-018-0350-z&volume=34&pages=289-295&publication_year=2019&author=Duarte-Rojo%2CA)

14. Lv, X. H., Lu, Q., Deng, K., Yang, J. L. & Yang, L. Prevalence and characteristics of covert/minimal hepatic encephalopathy in patients with liver cirrhosis: a systematic review and meta-analysis. _Am. J. Gastroenterol._ **119**, 690–699 (2024).

    [Article](https://doi.org/10.14309%2Fajg.0000000000002563) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB2cXnsVGktLc%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=37856206) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Prevalence%20and%20characteristics%20of%20covert%2Fminimal%20hepatic%20encephalopathy%20in%20patients%20with%20liver%20cirrhosis%3A%20a%20systematic%20review%20and%20meta-analysis&journal=Am.%20J.%20Gastroenterol.&doi=10.14309%2Fajg.0000000000002563&volume=119&pages=690-699&publication_year=2024&author=Lv%2CXH&author=Lu%2CQ&author=Deng%2CK&author=Yang%2CJL&author=Yang%2CL)

15. Weissenborn, K., Ennen, J. C., Schomerus, H., Rückert, N. & Hecker, H. Neuropsychological characterization of hepatic encephalopathy. _J. Hepatol._ **34**, 768–773 (2001).

    [Article](https://doi.org/10.1016%2FS0168-8278%2801%2900026-5) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DC%2BD38%2Fhslehtg%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=11434627) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Neuropsychological%20characterization%20of%20hepatic%20encephalopathy&journal=J.%20Hepatol.&doi=10.1016%2FS0168-8278%2801%2900026-5&volume=34&pages=768-773&publication_year=2001&author=Weissenborn%2CK&author=Ennen%2CJC&author=Schomerus%2CH&author=R%C3%BCckert%2CN&author=Hecker%2CH)

16. Karanfilian, B. V., Park, T., Senatore, F. & Rustgi, V. K. Minimal hepatic encephalopathy. _Clin. Liver Dis._ **24**, 209–218 (2020).

    [Article](https://doi.org/10.1016%2Fj.cld.2020.01.012) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32245528) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Minimal%20hepatic%20encephalopathy&journal=Clin.%20Liver%20Dis.&doi=10.1016%2Fj.cld.2020.01.012&volume=24&pages=209-218&publication_year=2020&author=Karanfilian%2CBV&author=Park%2CT&author=Senatore%2CF&author=Rustgi%2CVK)

17. Bloom, P. P. et al. HEAR-MHE study: Automated speech analysis identifies minimal hepatic encephalopathy and may predict future overt hepatic encephalopathy. _Hepatology_ **81**, 1740−1752 (2024).

18. Redford, M. A. _The Handbook of Speech Production. The Handbook of Speech Production_ Illustrated edition, Vol. 616 (John Wiley & Sons, 2015).

19. Collins, G. S., Reitsma, J. B., Altman, D. G. & Moons, K. G. M. Transparent reporting of a multivariable prediction model for individual prognosis or diagnosis (TRIPOD): the TRIPOD statement. _Ann. Intern. Med._ **131**, 211–219 (2015).

    [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Transparent%20reporting%20of%20a%20multivariable%20prediction%20model%20for%20individual%20prognosis%20or%20diagnosis%20%28TRIPOD%29%3A%20the%20TRIPOD%20statement&journal=Ann.%20Intern.%20Med.&volume=131&pages=211-219&publication_year=2015&author=Collins%2CGS&author=Reitsma%2CJB&author=Altman%2CDG&author=Moons%2CKGM)

20. Bajaj, J. S. et al. The stroop smartphone application is a short and valid method to screen for minimal hepatic encephalopathy. _Hepatology_ **58**, 1122–1132 (2013).

    [Article](https://doi.org/10.1002%2Fhep.26309) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=23389962) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20stroop%20smartphone%20application%20is%20a%20short%20and%20valid%20method%20to%20screen%20for%20minimal%20hepatic%20encephalopathy&journal=Hepatology&doi=10.1002%2Fhep.26309&volume=58&pages=1122-1132&publication_year=2013&author=Bajaj%2CJS)

21. Amodio, P. et al. Detection of minimal hepatic encephalopathy: normalization and optimization of the psychometric hepatic encephalopathy score. A neuropsychological and quantified EEG study. _J Hepatol_ **49**, 346–353 (2008).

    [Article](https://doi.org/10.1016%2Fj.jhep.2008.04.022) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=18602716) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Detection%20of%20minimal%20hepatic%20encephalopathy%3A%20normalization%20and%20optimization%20of%20the%20psychometric%20hepatic%20encephalopathy%20score.%20A%20neuropsychological%20and%20quantified%20EEG%20study&journal=J%20Hepatol&doi=10.1016%2Fj.jhep.2008.04.022&volume=49&pages=346-353&publication_year=2008&author=Amodio%2CP)

22. Gerratt, B. R., Kreiman, J. & Garellek, M. Comparing measures of voice quality from sustained phonation and continuous speech. _J. Speech Lang. Hearing Res._ **59**, 994–1001 (2016).

    [Article](https://doi.org/10.1044%2F2016_JSLHR-S-15-0307) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Comparing%20measures%20of%20voice%20quality%20from%20sustained%20phonation%20and%20continuous%20speech&journal=J.%20Speech%20Lang.%20Hearing%20Res.&doi=10.1044%2F2016_JSLHR-S-15-0307&volume=59&pages=994-1001&publication_year=2016&author=Gerratt%2CBR&author=Kreiman%2CJ&author=Garellek%2CM)

23. Tsanas, A., Little, M. A., McSharry, P. E., Spielman, J. & Ramig, L. O. Novel speech signal processing algorithms for high-accuracy classification of Parkinsons disease. _IEEE Trans. Biomed. Eng_ **59**, 1264–1271 (2012).

    [Article](https://doi.org/10.1109%2FTBME.2012.2183367) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=22249592) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Novel%20speech%20signal%20processing%20algorithms%20for%20high-accuracy%20classification%20of%20Parkinsons%20disease&journal=IEEE%20Trans.%20Biomed.%20Eng&doi=10.1109%2FTBME.2012.2183367&volume=59&pages=1264-1271&publication_year=2012&author=Tsanas%2CA&author=Little%2CMA&author=McSharry%2CPE&author=Spielman%2CJ&author=Ramig%2CLO)

24. Vashkevich, M. & Rushkevich, Y. Classification of ALS patients based on acoustic analysis of sustained vowel phonations. _Biomed. Signal Process Control_ **65**, 102350 (2021).

    [Article](https://doi.org/10.1016%2Fj.bspc.2020.102350) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Classification%20of%20ALS%20patients%20based%20on%20acoustic%20analysis%20of%20sustained%20vowel%20phonations&journal=Biomed.%20Signal%20Process%20Control&doi=10.1016%2Fj.bspc.2020.102350&volume=65&publication_year=2021&author=Vashkevich%2CM&author=Rushkevich%2CY)

25. Sapir, S., Ramig, L. O., Spielman, J. L. & Fox, C. Formant centralization ratio: a proposal for a new acoustic measure of dysarthric speech. _J. Speech Lang. Hearing Res._ **53**, 114–125 (2010).

    [Article](https://doi.org/10.1044%2F1092-4388%282009%2F08-0184%29) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Formant%20centralization%20ratio%3A%20a%20proposal%20for%20a%20new%20acoustic%20measure%20of%20dysarthric%20speech&journal=J.%20Speech%20Lang.%20Hearing%20Res.&doi=10.1044%2F1092-4388%282009%2F08-0184%29&volume=53&pages=114-125&publication_year=2010&author=Sapir%2CS&author=Ramig%2CLO&author=Spielman%2CJL&author=Fox%2CC)

26. Gómez-Vilda, P. et al. Assessing laryngeal neuromotor activity from phonation. _Int. J. Neural Syst._ **35**, 2550029 (2025).

27. Mekyska, J. et al. Robust and complex approach of pathological speech signal analysis. _Neurocomputing_ **167**, 94–111 (2015).

    [Article](https://doi.org/10.1016%2Fj.neucom.2015.02.085) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Robust%20and%20complex%20approach%20of%20pathological%20speech%20signal%20analysis&journal=Neurocomputing&doi=10.1016%2Fj.neucom.2015.02.085&volume=167&pages=94-111&publication_year=2015&author=Mekyska%2CJ)

28. Varma, S. & Simon, R. Bias in error estimation when using cross-validation for model selection. _BMC Bioinform._ **7**, 91 (2006).

    [Article](https://link.springer.com/doi/10.1186/1471-2105-7-91) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Bias%20in%20error%20estimation%20when%20using%20cross-validation%20for%20model%20selection&journal=BMC%20Bioinform.&doi=10.1186%2F1471-2105-7-91&volume=7&publication_year=2006&author=Varma%2CS&author=Simon%2CR)

29. Lundberg, S. M. et al. From local explanations to global understanding with explainable AI for trees. _Nat. Mach. Intell._ **2**, 56–67 (2020).

    [Article](https://doi.org/10.1038%2Fs42256-019-0138-9) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32607472) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7326367) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=From%20local%20explanations%20to%20global%20understanding%20with%20explainable%20AI%20for%20trees&journal=Nat.%20Mach.%20Intell.&doi=10.1038%2Fs42256-019-0138-9&volume=2&pages=56-67&publication_year=2020&author=Lundberg%2CSM)


[Download references](https://citation-needed.springer.com/v2/references/10.1038/s41746-025-02276-9?format=refman&flavour=references)

## Acknowledgements

This work was supported by the EU NextGenerationEU through the Recovery and Resilience Plan for Slovakia, under the project No. 09I05-03-V05-00044, and Instituto de Salud Carlos III, under the project No. PI21/00131.

## Author information

Author notes

1. These authors contributed equally: Anna Baiges, Peter Jarcuska.


### Authors and Affiliations

1. 2nd Department of Internal Medicine, Pavol Jozef Safarik University and L Pasteur University in Kosice, Trieda SNP 1, 040 11, Kosice, Slovakia

Jakub Gazda, Sylvia Drazilova, Martin Janicko & Peter Jarcuska

2. Barcelona Hepatic Hemodynamic Laboratory, Liver Unit, Hospital Clínic Barcelona, Institut de Investigacions Biomediques August Pi i Sunyer (IDIBAPS). CIBEREHD (Centro de Investigacion Biomedica en Red Enfermedades Hepaticas y Digestivas). Health Care Provider of the European Reference Network on Rare Liver Disorders (ERN RARE-Liver). Departament de Medicina i Ciencies de la Salut. Universidad de Barcelona, Barcelona, Spain

Juan Carlos García-Pagán & Anna Baiges

3. Intelligent Information Systems Lab, Technical University of Kosice, Letna 9, 042 00, Kosice, Slovakia

Peter Drotar, Mate Hires & Matej Gazda


Authors

1. Jakub Gazda


[View author publications](https://www.nature.com/search?author=Jakub%20Gazda)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Jakub%20Gazda) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Jakub%20Gazda%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

2. Juan Carlos García-Pagán


[View author publications](https://www.nature.com/search?author=Juan%20Carlos%20Garc%C3%ADa-Pag%C3%A1n)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Juan%20Carlos%20Garc%C3%ADa-Pag%C3%A1n) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Juan%20Carlos%20Garc%C3%ADa-Pag%C3%A1n%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

3. Sylvia Drazilova


[View author publications](https://www.nature.com/search?author=Sylvia%20Drazilova)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Sylvia%20Drazilova) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Sylvia%20Drazilova%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

4. Peter Drotar


[View author publications](https://www.nature.com/search?author=Peter%20Drotar)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Peter%20Drotar) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Peter%20Drotar%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

5. Mate Hires


[View author publications](https://www.nature.com/search?author=Mate%20Hires)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Mate%20Hires) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Mate%20Hires%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

6. Matej Gazda


[View author publications](https://www.nature.com/search?author=Matej%20Gazda)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Matej%20Gazda) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Matej%20Gazda%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

7. Martin Janicko


[View author publications](https://www.nature.com/search?author=Martin%20Janicko)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Martin%20Janicko) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Martin%20Janicko%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

8. Anna Baiges


[View author publications](https://www.nature.com/search?author=Anna%20Baiges)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Anna%20Baiges) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Anna%20Baiges%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

9. Peter Jarcuska


[View author publications](https://www.nature.com/search?author=Peter%20Jarcuska)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Peter%20Jarcuska) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Peter%20Jarcuska%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)


### Contributions

Conceptualization: P.J., Methodology; J.G., J.C.G.P., P.D., A.B., P.J.; Analysis: J.G., P.D., M.H., M.G.; Data Curation: J.G., M.J., S.D.; Supervision: J.C.G.P., A.B., P.J.; Writin—Original Draft: J.G., J.C.G.P., S.D., M.J.; Writing—Critical Review and Editing: J.C.G.P., A.B., P.J. All authors have read and approved the manuscript.

### Corresponding author

Correspondence to
[Martin Janicko](mailto:martin.janicko@upjs.sk).

## Ethics declarations

### Competing interests

The authors declare no competing interests.

## Additional information

**Publisher’s note** Springer Nature remains neutral with regard to jurisdictional claims in published maps and institutional affiliations.

## Rights and permissions

**Open Access** This article is licensed under a Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License, which permits any non-commercial use, sharing, distribution and reproduction in any medium or format, as long as you give appropriate credit to the original author(s) and the source, provide a link to the Creative Commons licence, and indicate if you modified the licensed material. You do not have permission under this licence to share adapted material derived from this article or parts of it. The images or other third party material in this article are included in the article’s Creative Commons licence, unless indicated otherwise in a credit line to the material. If material is not included in the article’s Creative Commons licence and your intended use is not permitted by statutory regulation or exceeds the permitted use, you will need to obtain permission directly from the copyright holder. To view a copy of this licence, visit [http://creativecommons.org/licenses/by-nc-nd/4.0/](http://creativecommons.org/licenses/by-nc-nd/4.0/).

[Reprints and permissions](https://s100.copyright.com/AppDispatchServlet?title=Prospective%20evaluation%20of%20speech%20as%20a%20digital%20biomarker%20for%20covert%20hepatic%20encephalopathy&author=Jakub%20Gazda%20et%20al&contentID=10.1038%2Fs41746-025-02276-9&copyright=The%20Author%28s%29&publication=2398-6352&publicationDate=2025-12-22&publisherName=SpringerNature&orderBeanReset=true&oa=CC%20BY-NC-ND)

## About this article

[![Check for updates. Verify currency and authenticity via CrossMark](<Base64-Image-Removed>)](https://crossmark.crossref.org/dialog/?doi=10.1038/s41746-025-02276-9)

### Cite this article

Gazda, J., García-Pagán, J.C., Drazilova, S. _et al._ Prospective evaluation of speech as a digital biomarker for covert hepatic encephalopathy.
_npj Digit. Med._ **8**, 788 (2025). https://doi.org/10.1038/s41746-025-02276-9

[Download citation](https://citation-needed.springer.com/v2/references/10.1038/s41746-025-02276-9?format=refman&flavour=citation)

- Received: 23 September 2025

- Accepted: 10 December 2025

- Published: 22 December 2025

- Version of record: 29 December 2025

- DOI: https://doi.org/10.1038/s41746-025-02276-9


### Share this article

Anyone you share the following link with will be able to read this content:

Get shareable link

Sorry, a shareable link is not currently available for this article.

Copy shareable link to clipboard

Provided by the Springer Nature SharedIt content-sharing initiative


### Subjects

- [Biomarkers](https://www.nature.com/subjects/biomarkers)
- [Diseases](https://www.nature.com/subjects/diseases)
- [Gastroenterology](https://www.nature.com/subjects/gastroenterology)
- [Medical research](https://www.nature.com/subjects/medical-research)

Close bannerClose

![Nature Briefing: Translational Research](https://www.nature.com/static/images/logos/nature-briefing-logo-transres-white-09b7a7a727.svg)

Sign up for the _Nature Briefing: Translational Research_ newsletter — top stories in biotechnology, drug discovery and pharma.

Email address

Sign up

I agree my information will be processed in accordance with the _Nature_ and Springer Nature Limited [Privacy Policy](https://www.nature.com/info/privacy).

Close bannerClose

Get what matters in translational research, free to your inbox weekly. [Sign up for Nature Briefing: Translational Research](https://www.nature.com/briefing/translational-research/?brieferEntryPoint=TransResBriefingBanner)